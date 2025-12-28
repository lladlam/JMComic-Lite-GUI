"""
独立 GUI 程序，依赖同目录下的 jm_api.py
"""
import threading
import gc
import concurrent.futures
import time
import math
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from io import BytesIO

import requests
from PIL import Image, ImageTk

from jm_api import (
    parse_to_jm_id,
    format_album_url,
    analyse_jm_album_html,
    get_album_cover_url,
    PROJECT_JMCONFIG,
    get_all_image_details,
    get_all_image_urls,
)


class LiteGuiApp:
    def __init__(self, master):
        self.master = master
        master.title('JMComic Crawler - Lite')
        # enforce a sensible minimum window size so layout remains usable
        master.minsize(600, 400)

        frm = ttk.Frame(master, padding=10)
        frm.grid(sticky='nsew')
        # make master and frm resizeable and adaptive
        master.columnconfigure(0, weight=1)
        master.columnconfigure(1, weight=1)
        # give room for info/debug/search areas to expand when window is resized
        for r in range(0, 16):
            master.rowconfigure(r, weight=1 if r in (3, 5, 7, 11) else 0)
        frm.grid_columnconfigure(0, weight=1)
        frm.grid_columnconfigure(1, weight=1)
        # allow info, debug and search results to expand
        frm.grid_rowconfigure(3, weight=1)
        frm.grid_rowconfigure(5, weight=1)
        frm.grid_rowconfigure(11, weight=1)

        ttk.Label(frm, text='请输入 JM 车号 或 本子 URL:').grid(column=0, row=0, sticky='w')
        self.entry = ttk.Entry(frm, width=50)
        self.entry.grid(column=0, row=1, sticky='we', pady=6)

        # search box
        ttk.Label(frm, text='站内搜索:').grid(column=0, row=8, sticky='w')
        self.search_entry = ttk.Entry(frm, width=40)
        self.search_entry.grid(column=0, row=9, sticky='we')
        self.search_btn = ttk.Button(frm, text='搜索', command=self.on_search)
        self.search_btn.grid(column=0, row=10, sticky='w')
        self.search_results = tk.Listbox(frm, height=6, width=60)
        self.search_results.grid(column=0, row=11, sticky='nsew')
        self.search_results.bind('<<ListboxSelect>>', self.on_search_select)
        # search filter
        ttk.Label(frm, text='搜索过滤 (标题包含):').grid(column=0, row=12, sticky='w')
        self.search_filter = ttk.Entry(frm, width=40)
        self.search_filter.grid(column=0, row=13, sticky='we')
        ttk.Button(frm, text='应用过滤', command=self.apply_search_filter).grid(column=0, row=14, sticky='w')

        btn_frame = ttk.Frame(frm)
        btn_frame.grid(column=0, row=2, sticky='w')
        ttk.Button(btn_frame, text='获取详情', command=self.on_fetch).grid(column=0, row=0)
        ttk.Button(btn_frame, text='保存封面...', command=self.on_save_cover).grid(column=1, row=0, padx=6)
        ttk.Button(btn_frame, text='查看封面', command=self.on_cover_click).grid(column=2, row=0, padx=6)
        ttk.Button(btn_frame, text='Debug: Fetch 1212975', command=self.on_debug_fetch).grid(column=3, row=0, padx=6)
        # 显示所有图片功能（点击后会显示图片面板并异步加载图片）
        self.show_all_btn = ttk.Button(btn_frame, text='显示所有图片', command=self.on_show_all_images)
        self.show_all_btn.grid(column=4, row=0, padx=6)
        ttk.Button(btn_frame, text='全部下载并重组', command=self.on_download_all).grid(column=5, row=0, padx=6)

        self.info = tk.Text(frm, width=60, height=10)
        self.info.grid(column=0, row=3, pady=8, sticky='nsew')

        # create a vertical scroll area that will contain the cover and all images stacked vertically
        self.scroll_frame = ttk.Frame(frm)
        self.scroll_frame.grid(column=1, row=0, rowspan=7, padx=10, sticky='nsew')
        # hide images panel by default to reduce initial window size
        self.scroll_frame.grid_remove()

        # canvas 为自适应大小（不再使用固定宽高），内部 frame 用于堆叠图片
        self.vcanvas = tk.Canvas(self.scroll_frame, highlightthickness=0)
        self.vscroll = ttk.Scrollbar(self.scroll_frame, orient='vertical', command=self.vcanvas.yview)
        self.vinner = ttk.Frame(self.vcanvas)
        self.vinner_id = self.vcanvas.create_window((0, 0), window=self.vinner, anchor='nw')
        self.vcanvas.configure(yscrollcommand=self.vscroll.set)
        self.vcanvas.grid(row=0, column=0, sticky='nsew')
        self.vscroll.grid(row=0, column=1, sticky='ns')
        # allow canvas/inner frame to resize and keep scrollregion updated
        self.vinner.bind('<Configure>', lambda e: self.vcanvas.configure(scrollregion=self.vcanvas.bbox('all')))
        self.scroll_frame.grid_columnconfigure(0, weight=1)
        self.scroll_frame.grid_rowconfigure(0, weight=1)

        # cover label goes inside the scrollable inner frame
        self.cover_label = ttk.Label(self.vinner)
        self.cover_label.pack(side='top', pady=6)
        # allow clicking the cover to preview and save
        self.cover_label.bind('<Button-1>', lambda e: self.on_cover_click())

        self.thumb_images = []

        # debug area
        ttk.Label(frm, text='Debug 输出:').grid(column=0, row=4, sticky='w')
        self.debug_text = tk.Text(frm, width=60, height=10, bg='#111', fg='#0f0')
        self.debug_text.grid(column=0, row=5, pady=8, sticky='nsew')
        # progress area: use a frame so elements adapt to window width
        self.progress_frame = ttk.Frame(frm)
        self.progress_frame.grid(column=0, row=7, pady=6, sticky='we')
        self.progress_frame.grid_columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(self.progress_frame, orient='horizontal', mode='determinate')
        self.progress.grid(column=0, row=0, sticky='we')
        self.progress_label = ttk.Label(self.progress_frame, text='进度: 0/0')
        self.progress_label.grid(column=1, row=0, padx=8, sticky='e')
        self.speed_label = ttk.Label(self.progress_frame, text='速度: 0 KB/s')
        self.speed_label.grid(column=2, row=0, padx=8, sticky='e')
        self.eta_label = ttk.Label(self.progress_frame, text='剩余: 0s')
        self.eta_label.grid(column=3, row=0, padx=8, sticky='e')
        self.cancel_download_btn = ttk.Button(self.progress_frame, text='取消下载', command=lambda: self.cancel_download(True))
        self.cancel_download_btn.grid(column=4, row=0, padx=8, sticky='e')

        # state
        self.current_cover_image = None
        self.current_album_id = None
        # pagination and thumbnails
        self.image_details = []
        self.page_size = 12
        self.page_index = 0
        self.download_executor = None
        self.download_cancel_flag = False

    def on_fetch(self):
        text = self.entry.get().strip()
        if not text:
            messagebox.showwarning('提示', '请输入车号或URL')
            return

        t = threading.Thread(target=self.fetch_and_show, args=(text,), daemon=True)
        t.start()

    def fetch_and_show(self, text):
        try:
            aid = parse_to_jm_id(text)
            self.current_album_id = aid

            self.debug_log(f'解析到车号: {aid}')

            # use project domain resolution and Postman when available to handle anti-scraping
            domain = None
            postman = None
            try:
                if PROJECT_JMCONFIG is not None:
                    domain = PROJECT_JMCONFIG.get_html_domain()
                    url = format_album_url(aid, domain)
                    headers = PROJECT_JMCONFIG.new_html_headers(domain)
                    postman = PROJECT_JMCONFIG.new_postman(session=True)
                    self.debug_log(f'使用项目 Postman 请求: {url} (domain={domain})')
                    resp = postman.get(url, headers=headers, timeout=15)
                else:
                    raise RuntimeError('PROJECT_JMCONFIG 未加载')
            except Exception as ex:
                # fallback to simple requests
                self.debug_log(f'项目 Postman 请求失败，回退到 requests: {ex}')
                url = format_album_url(aid)
                headers = {'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9', 'user-agent': 'Mozilla/5.0'}
                self.debug_log(f'请求 URL: {url}')
                resp = requests.get(url, headers=headers, timeout=15)

            resp.raise_for_status()

            self.debug_log(f'HTTP 状态: {resp.status_code}, 响应长度: {len(resp.text)}')

            album = analyse_jm_album_html(resp.text)

            info_lines = []
            info_lines.append(f'标题: {getattr(album, "name", "")}')
            info_lines.append(f'作者: {getattr(album, "authors", "")}')
            info_lines.append(f'页数: {getattr(album, "page_count", "")}')
            info_lines.append(f'描述: {getattr(album, "description", "")[:300]}')
            info_text = '\n'.join(info_lines)

            self.master.after(0, lambda: self.info_delete_insert(info_text))

            # 下载封面并显示
            cover_url = get_album_cover_url(aid)
            self.debug_log(f'下载封面: {cover_url}')
            try:
                if postman is not None:
                    img_headers = PROJECT_JMCONFIG.new_html_headers(domain) if PROJECT_JMCONFIG is not None and domain is not None else headers
                    img_resp = postman.get(cover_url, headers=img_headers, timeout=15)
                else:
                    img_resp = requests.get(cover_url, headers=headers, timeout=15)
            except Exception:
                img_resp = requests.get(cover_url, headers=headers, timeout=15)
            img_resp.raise_for_status()
            img = Image.open(BytesIO(img_resp.content)).convert('RGB')
            img.thumbnail((360, 480))
            self.current_cover_image = img
            tk_img = ImageTk.PhotoImage(img)
            # capture tk_img in default arg to avoid closure issues when called later on main thread
            def set_cover(img=tk_img):
                self.cover_label.configure(image=img)
                setattr(self.cover_label, 'image', img)
                # 自动显示右侧图片面板以便预览封面和后续缩略图
                try:
                    self.scroll_frame.grid()
                except Exception:
                    pass
                return

            self.master.after(0, set_cover)

        except Exception as e:
            msg = str(e)
            self.debug_log(f'错误: {msg}')
            self.master.after(0, lambda m=msg: messagebox.showerror('错误', m))

    def debug_log(self, s: str):
        # append to debug text from any thread
        self.master.after(0, lambda text=s: (self.debug_text.insert(tk.END, text + '\n'), self.debug_text.see(tk.END)))

    def on_debug_fetch(self):
        # run debug fetch for ID 1212975
        t = threading.Thread(target=self.debug_fetch_1212975, daemon=True)
        t.start()

    def debug_fetch_1212975(self):
        try:
            aid = '1212975'
            self.debug_log('开始 Debug 流程 for ID 1212975')

            # If project config available, use its domain resolution
            if PROJECT_JMCONFIG is not None:
                try:
                    self.debug_log('使用项目原版域名解析: JmModuleConfig.get_html_domain()')
                    domain = PROJECT_JMCONFIG.get_html_domain()
                    self.debug_log(f'解析到 HTML 域名: {domain}')
                except Exception as e:
                    self.debug_log(f'域名解析失败: {e}')
            else:
                self.debug_log('项目原版配置不可用，使用内置域名')

            # try using project postman/domain first
            try:
                if PROJECT_JMCONFIG is not None:
                    domain = PROJECT_JMCONFIG.get_html_domain()
                    url = format_album_url(aid, domain)
                    headers = PROJECT_JMCONFIG.new_html_headers(domain)
                    postman = PROJECT_JMCONFIG.new_postman(session=True)
                    self.debug_log(f'使用项目 Postman 请求: {url} (domain={domain})')
                    resp = postman.get(url, headers=headers, timeout=20)
                else:
                    raise RuntimeError('PROJECT_JMCONFIG 未加载')
            except Exception as ex:
                self.debug_log(f'项目 Postman 请求失败，回退到 requests: {ex}')
                url = format_album_url(aid)
                headers = {'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9', 'user-agent': 'Mozilla/5.0'}
                self.debug_log(f'开始请求详情页: {url}')
                resp = requests.get(url, headers=headers, timeout=20)

            self.debug_log(f'响应状态: {resp.status_code}')
            resp.raise_for_status()

            album = analyse_jm_album_html(resp.text)
            self.debug_log(f'解析到标题: {getattr(album, "name", "")}')

            cover = get_album_cover_url(aid)
            self.debug_log(f'封面 URL 推断为: {cover}')

        except Exception as e:
            self.debug_log(f'Debug 错误: {e}')

    def info_delete_insert(self, text):
        self.info.delete('1.0', tk.END)
        self.info.insert(tk.END, text)

    def on_search(self):
        q = self.search_entry.get().strip()
        if not q:
            return
        # disable button and show debug
        self.search_btn.state(['disabled'])
        self.debug_log(f'开始搜索: {q}')
        t = threading.Thread(target=self._do_search, args=(q,), daemon=True)
        t.start()

    def _do_search(self, q):
        try:
            from jm_api import search_albums
            results = search_albums(q)
            self.master.after(0, lambda: self._populate_search_results(results))
        except Exception as e:
            self.debug_log(f'search error: {e}')
        finally:
            # re-enable button
            self.master.after(0, lambda: self.search_btn.state(['!disabled']))

    def _populate_search_results(self, results):
        # results: list of (aid, title, authors, tags, category)
        self.last_search_results = results
        self.search_results.delete(0, tk.END)
        for aid, title, authors, tags, category in results:
            authors_str = ','.join(authors) if authors else ''
            tags_str = ','.join(tags) if tags else ''
            display = f'{aid} | {title} | 作者: {authors_str} | 标签: {tags_str}'
            self.search_results.insert(tk.END, display)

    def on_search_select(self, evt):
        w = evt.widget
        if not w.curselection():
            return
        idx = int(w.curselection()[0])
        val = w.get(idx)
        aid = val.split()[0]
        # populate entry and fetch
        self.entry.delete(0, tk.END)
        self.entry.insert(0, aid)
        self.on_fetch()

    def apply_search_filter(self):
        filt = self.search_filter.get().strip().lower()
        if not hasattr(self, 'last_search_results'):
            return
        if not filt:
            results = self.last_search_results
        else:
            results = [r for r in self.last_search_results if filt in r[1].lower()]
        self._populate_search_results(results)

    def cancel_download(self, flag: bool):
        self.download_cancel_flag = flag

    def on_show_all_images(self):
        if not self.current_album_id:
            messagebox.showwarning('提示', '请先获取详情或输入车号')
            return
        # 显示图片面板并异步加载全部图片（可能较耗时）
        self.scroll_frame.grid()
        t = threading.Thread(target=self._load_and_show_images, args=(self.current_album_id,), daemon=True)
        t.start()

    def _prepare_images_for_pagination(self, aid):
        try:
            imgs = get_all_image_details(aid)
            self.image_details = imgs
            self.page_index = 0
            self.master.after(0, lambda: self.show_page(0))
        except Exception as e:
            self.debug_log(f'准备图片失败: {e}')

    def show_page(self, page_idx: int):
        total = len(self.image_details)
        if total == 0:
            return
        max_page = math.ceil(total / self.page_size) - 1
        page_idx = max(0, min(page_idx, max_page))
        self.page_index = page_idx
        start = page_idx * self.page_size
        end = min(start + self.page_size, total)
        page_items = self.image_details[start:end]

        # load thumbnails for page asynchronously
        def load_page():
            thumbs = []
            for img in page_items:
                try:
                    postman = PROJECT_JMCONFIG.new_postman(session=True)
                    resp = postman.get(img.download_url, headers=PROJECT_JMCONFIG.APP_HEADERS_IMAGE, timeout=20)
                    resp.raise_for_status()
                    imgdata = resp.content
                except Exception:
                    import requests
                    resp = requests.get(img.download_url, timeout=20)
                    resp.raise_for_status()
                    imgdata = resp.content

                from jm_api import decode_image_pil
                from jmcomic.jm_toolkit import JmImageTool
                try:
                    num = JmImageTool.get_num_by_detail(img)
                except Exception:
                    num = 0
                pil_img = decode_image_pil(imgdata, num)
                pil_img.thumbnail((160, 220))
                thumbs.append((pil_img, img.filename, img))

            def render():
                # clear existing
                for w in self.vinner.winfo_children():
                    w.destroy()
                self.thumb_images.clear()
                # cover should remain at top
                if self.current_cover_image is not None:
                    tk_cover = ImageTk.PhotoImage(self.current_cover_image)
                    self.cover_label.configure(image=tk_cover)
                    self.cover_label.image = tk_cover

                # arrange thumbnails in a responsive grid based on canvas width
                preferred_w = 180
                canvas_w = self.vcanvas.winfo_width() or self.master.winfo_width() or preferred_w * 3
                cols = max(1, int(canvas_w / preferred_w))
                for c in range(cols):
                    try:
                        self.vinner.grid_columnconfigure(c, weight=1)
                    except Exception:
                        pass

                for idx, (pil_img, caption, img_detail) in enumerate(thumbs):
                    tkimg = ImageTk.PhotoImage(pil_img)
                    frame = ttk.Frame(self.vinner)
                    lbl = ttk.Label(frame, image=tkimg, text=caption, compound='top')
                    lbl.pack()
                    r = idx // cols
                    cc = idx % cols
                    frame.grid(row=r, column=cc, padx=6, pady=6, sticky='n')
                    lbl.bind('<Button-1>', lambda e, d=img_detail: self.on_thumbnail_click(d))
                    self.thumb_images.append(tkimg)
                    try:
                        pil_img.close()
                    except Exception:
                        pass

                # add pagination controls
                nav = ttk.Frame(self.vinner)
                nav.pack()
                prev_btn = ttk.Button(nav, text='上一页', command=lambda: self.show_page(self.page_index - 1))
                next_btn = ttk.Button(nav, text='下一页', command=lambda: self.show_page(self.page_index + 1))
                prev_btn.pack(side='left')
                next_btn.pack(side='left')

                self.vinner.update_idletasks()
                bbox = self.vcanvas.bbox(self.vinner_id)
                if bbox:
                    self.vcanvas.configure(scrollregion=bbox)

            self.master.after(0, render)

        threading.Thread(target=load_page, daemon=True).start()

    def _load_and_show_images(self, aid):
        try:
            imgs = get_all_image_details(aid)
            self.debug_log(f'图片数量: {len(imgs)}')
            total = len(imgs)
            # setup progress
            self.master.after(0, lambda: self.progress.configure(maximum=total, value=0))
            # fetch binary data and create thumbnails in background thread
            thumbs = []  # list of (tkimage, caption)
            for idx, img in enumerate(imgs):
                try:
                    postman = PROJECT_JMCONFIG.new_postman(session=True)
                    resp = postman.get(img.download_url, headers=PROJECT_JMCONFIG.APP_HEADERS_IMAGE, timeout=20)
                    resp.raise_for_status()
                    imgdata = resp.content
                except Exception:
                    import requests
                    resp = requests.get(img.download_url, timeout=20)
                    resp.raise_for_status()
                    imgdata = resp.content

                # need to decode using split-and-merge logic
                from jm_api import decode_image_pil
                # determine split num
                try:
                    from jmcomic.jm_toolkit import JmImageTool
                    num = JmImageTool.get_num_by_detail(img)
                except Exception:
                    num = 0

                pil_img = decode_image_pil(imgdata, num)
                pil_img.thumbnail((160, 220))
                thumbs.append((pil_img, img.filename, img))
                # update progress
                self.master.after(0, lambda v=idx+1: self.progress.configure(value=v))

            # update UI on main thread
            def render_thumbs():
                for w in self.vinner.winfo_children():
                    w.destroy()
                self.thumb_images.clear()

                # arrange thumbnails in a responsive grid
                preferred_w = 180
                canvas_w = self.vcanvas.winfo_width() or self.master.winfo_width() or preferred_w * 3
                cols = max(1, int(canvas_w / preferred_w))
                for c in range(cols):
                    try:
                        self.vinner.grid_columnconfigure(c, weight=1)
                    except Exception:
                        pass

                for i, (pil_img, caption, img_detail) in enumerate(thumbs):
                    tkimg = ImageTk.PhotoImage(pil_img)
                    frame = ttk.Frame(self.vinner)
                    lbl = ttk.Label(frame, image=tkimg, text=caption, compound='top')
                    lbl.pack()
                    r = i // cols
                    cc = i % cols
                    frame.grid(row=r, column=cc, padx=6, pady=6, sticky='n')
                    # bind click to preview full image
                    lbl.bind('<Button-1>', lambda e, d=img_detail: self.on_thumbnail_click(d))
                    self.thumb_images.append(tkimg)
                    # free pil_img memory
                    try:
                        pil_img.close()
                    except Exception:
                        pass

                # hint to GC
                gc.collect()

                # update canvas scroll region and window size
                self.vinner.update_idletasks()
                bbox = self.vcanvas.bbox(self.vinner_id)
                if bbox:
                    self.vcanvas.configure(scrollregion=bbox)

            self.master.after(0, render_thumbs)
        except Exception as e:
            self.debug_log(f'加载图片失败: {e}')

    def on_download_all(self):
        if not self.current_album_id:
            messagebox.showwarning('提示', '请先获取详情或输入车号')
            return
        d = filedialog.askdirectory()
        if not d:
            return
        # start thread-pool managed download with progress and ETA
        t = threading.Thread(target=lambda: self._download_all_with_pool(self.current_album_id, d), daemon=True)
        t.start()

    def _download_all_with_pool(self, aid, save_dir, workers=5):
        try:
            imgs = get_all_image_details(aid)
            total = len(imgs)
            if total == 0:
                return
            self.download_cancel_flag = False
            self.master.after(0, lambda: self.progress.configure(maximum=total, value=0))
            start_time = time.time()
            completed = 0

            def task(img):
                if self.download_cancel_flag:
                    return False
                try:
                    postman = PROJECT_JMCONFIG.new_postman(session=True)
                    r = postman.get(img.download_url, headers=PROJECT_JMCONFIG.APP_HEADERS_IMAGE, timeout=60)
                    r.raise_for_status()
                    data = r.content
                except Exception:
                    import requests
                    r = requests.get(img.download_url, timeout=60)
                    r.raise_for_status()
                    data = r.content

                from jmcomic.jm_toolkit import JmImageTool
                try:
                    num = JmImageTool.get_num_by_detail(img)
                except Exception:
                    num = 0
                from jm_api import decode_image_pil
                pil_img = decode_image_pil(data, num)
                pil_img.save(f"{save_dir}/{img.filename}")
                return True

            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
                futures = {ex.submit(task, img): img for img in imgs}
                for fut in concurrent.futures.as_completed(futures):
                    if self.download_cancel_flag:
                        break
                    res = False
                    try:
                        res = fut.result()
                    except Exception as e:
                        self.debug_log(f'download error: {e}')
                    if res:
                        completed += 1
                        elapsed = time.time() - start_time
                        avg = elapsed / completed if completed else 0.0001
                        remaining = total - completed
                        eta = remaining * avg
                        speed = completed / elapsed if elapsed > 0 else 0
                        self.master.after(0, lambda c=completed, t=total, s=speed, e=eta: (
                            self.progress.configure(value=c),
                            self.progress_label.configure(text=f'进度: {c}/{t}'),
                            self.speed_label.configure(text=f'速度: {s:.2f} img/s'),
                            self.eta_label.configure(text=f'剩余: {int(e)}s')
                        ))

            if self.download_cancel_flag:
                self.debug_log('下载被取消')
            else:
                self.debug_log('全部下载完成')
        except Exception as e:
            self.debug_log(f'download manager error: {e}')

    def on_thumbnail_click(self, img_detail):
        # open preview window and fetch full-size decoded image asynchronously
        preview = tk.Toplevel(self.master)
        preview.title(img_detail.filename)
        lbl = ttk.Label(preview, text='加载中...')
        lbl.pack()

        # zoom controls
        zoom_frame = ttk.Frame(preview)
        zoom_frame.pack()
        zoom_in_btn = ttk.Button(zoom_frame, text='放大')
        zoom_out_btn = ttk.Button(zoom_frame, text='缩小')
        zoom_in_btn.pack(side='left')
        zoom_out_btn.pack(side='left')

        def fetch_and_show():
            try:
                postman = PROJECT_JMCONFIG.new_postman(session=True)
                resp = postman.get(img_detail.download_url, headers=PROJECT_JMCONFIG.APP_HEADERS_IMAGE, timeout=30)
                resp.raise_for_status()
                data = resp.content
            except Exception:
                import requests
                resp = requests.get(img_detail.download_url, timeout=30)
                resp.raise_for_status()
                data = resp.content

            try:
                from jmcomic.jm_toolkit import JmImageTool
                num = JmImageTool.get_num_by_detail(img_detail)
            except Exception:
                num = 0

            from jm_api import decode_image_pil
            pil_img = decode_image_pil(data, num)
            # keep original pil image for zoom
            orig = pil_img
            max_w = min(self.master.winfo_width(), 1200)
            max_h = min(self.master.winfo_height(), 1600)
            display = orig.copy()
            display.thumbnail((max_w, max_h))
            tkimg = ImageTk.PhotoImage(display)

            def show():
                lbl.configure(image=tkimg, text='')
                lbl.image = tkimg
                btn = ttk.Button(preview, text='保存此图', command=lambda: self._save_preview_image(pil_img, img_detail.filename))
                btn.pack()
                # zoom handlers
                def do_zoom(factor):
                    nonlocal display, tkimg
                    try:
                        w = int(display.width * factor)
                        h = int(display.height * factor)
                        tmp = orig.copy()
                        tmp.thumbnail((w, h))
                        tkimg = ImageTk.PhotoImage(tmp)
                        lbl.configure(image=tkimg)
                        lbl.image = tkimg
                    except Exception as ex:
                        self.debug_log(f'zoom error: {ex}')

                zoom_in_btn.configure(command=lambda: do_zoom(1.25))
                zoom_out_btn.configure(command=lambda: do_zoom(0.8))

            self.master.after(0, show)

        threading.Thread(target=fetch_and_show, daemon=True).start()

    def on_cover_click(self, event=None):
        """Preview and allow saving of the current cover image."""
        if self.current_cover_image is None:
            messagebox.showwarning('提示', '当前无封面，请先获取详情')
            return
        preview = tk.Toplevel(self.master)
        preview.title('封面预览')
        lbl = ttk.Label(preview)
        lbl.pack()
        img = self.current_cover_image.copy()
        max_w = min(self.master.winfo_width(), 1200)
        max_h = min(self.master.winfo_height(), 1600)
        img.thumbnail((max_w, max_h))
        tkimg = ImageTk.PhotoImage(img)
        lbl.configure(image=tkimg)
        lbl.image = tkimg
        ttk.Button(preview, text='保存封面...', command=self.on_save_cover).pack()

    def _save_preview_image(self, pil_img, filename):
        f = filedialog.asksaveasfilename(defaultextension='.jpg', initialfile=filename, filetypes=[('JPEG', '*.jpg'), ('PNG', '*.png')])
        if not f:
            return
        pil_img.save(f)
        messagebox.showinfo('完成', f'图片已保存: {f}')

    def on_save_cover(self):
        if self.current_cover_image is None:
            messagebox.showwarning('提示', '当前没有封面图片可保存，请先获取详情')
            return

        default_name = f'JM{self.current_album_id}_cover.jpg' if self.current_album_id else 'cover.jpg'
        f = filedialog.asksaveasfilename(defaultextension='.jpg', initialfile=default_name,
                                         filetypes=[('JPEG', '*.jpg'), ('PNG', '*.png')])
        if not f:
            return

        try:
            self.current_cover_image.save(f)
            messagebox.showinfo('完成', f'封面已保存到: {f}')
        except Exception as e:
            messagebox.showerror('错误', str(e))


if __name__ == '__main__':
    root = tk.Tk()
    root.geometry('600x400')
    root.minsize(600, 400)
    root.resizable(True, True)
    app = LiteGuiApp(root)
    root.mainloop()
