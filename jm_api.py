"""
轻量化实现：复制并封装项目中用于解析 album 的必要逻辑，避免直接依赖整个包结构。
提供：parse_to_jm_id, format_album_url, analyse_jm_album_html, get_album_cover_url
"""
from typing import Optional
import sys
import os
from base64 import b64decode
from re import compile

# 尝试使用项目原始解析逻辑（保留原版域名解析功能）
_USE_PROJECT_IMPL = False

try:
    # 把 src 目录加入 sys.path，以便导入 jmcomic 包
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    src_path = os.path.join(repo_root, 'src')
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

    from jmcomic.jm_toolkit import JmcomicText
    from jmcomic.jm_config import JmModuleConfig

    parse_to_jm_id = JmcomicText.parse_to_jm_id
    analyse_jm_album_html = JmcomicText.analyse_jm_album_html
    format_album_url = lambda aid, domain='18comic.vip': JmcomicText.format_url(f'/album/{aid}/', domain)
    get_album_cover_url = JmcomicText.get_album_cover_url

    # expose original config for debug usage
    PROJECT_JMCONFIG = JmModuleConfig
    _USE_PROJECT_IMPL = True
except Exception:
    # 回退到简化实现（仅在无法导入项目源码时使用）
    PROJECT_JMCONFIG = None

    pattern_html_b64_decode_content = compile(r'const html = base64DecodeUtf8\("(.*?)"\)')
    pattern_html_album_album_id = compile(r'<span class="number">.*?：JM(\d+)</span>')
    pattern_html_album_scramble_id = compile(r'var scramble_id = (\d+);')
    pattern_html_album_name = compile(r'id="book-name"[^>]*?>([\s\S]*?)<')
    pattern_html_album_description = compile(r'叙述：([\s\S]*?)</h2>')
    pattern_html_album_episode_list = compile(r'data-album="(\d+)"[^>]*>[^\S\s]*第(\d+)[话話]([\s\S]*?)<[^\S\s]*?>')
    pattern_html_album_page_count = compile(r'<span class="pagecount">.*?:(\d+)</span>')
    pattern_html_album_pub_date = compile(r'>上架日期 : (.*?)</span>')
    pattern_html_album_update_date = compile(r'>更新日期 : (.*?)</span>')
    pattern_html_tag_a = compile(r'<a[^>]*?>\s*(\S*)\s*</a>')

    class AlbumStub:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)


    def parse_to_jm_id(text) -> str:
        if isinstance(text, int):
            return str(text)

        if isinstance(text, str) and text.isdigit():
            return text

        # JM12345
        if isinstance(text, str) and len(text) >= 2 and (text[0] in ('J', 'j')) and (text[1] in ('M', 'm')):
            return text[2:]

        # try to find /photo/ or /album/ id
        for p in [compile(r'(photos?|albums?)/(\d+)'), compile(r'id=(\d+)')]:
            m = p.search(text)
            if m:
                return m[2] if len(m.groups()) >= 2 else m[1]

        raise ValueError(f'无法解析jm车号: {text}')


    def parse_jm_base64_html(resp_text: str) -> str:
        match = pattern_html_b64_decode_content.search(resp_text)
        if not match:
            return resp_text
        html_b64 = match[1]
        return b64decode(html_b64).decode()


    def match_field(field_name: str, pattern, text):
        if isinstance(pattern, list):
            last_pattern = pattern[-1]
            for i in range(0, len(pattern) - 1):
                match = pattern[i].search(text)
                if match is None:
                    return None
                text = match[0]
            return last_pattern.findall(text)

        if field_name.endswith('_list'):
            return pattern.findall(text)
        else:
            m = pattern.search(text)
            if m:
                return m[1]
            return None


    def analyse_jm_album_html(html: str) -> AlbumStub:
        html = parse_jm_base64_html(html)
        patterns = {
            'album_id': pattern_html_album_album_id,
            'scramble_id': pattern_html_album_scramble_id,
            'name': pattern_html_album_name,
            'description': pattern_html_album_description,
            'episode_list': pattern_html_album_episode_list,
            'page_count': pattern_html_album_page_count,
            'pub_date': pattern_html_album_pub_date,
            'update_date': pattern_html_album_update_date,
            'tags': [compile(r'<span itemprop="genre" data-type="tags">([\s\S]*?)</span>'), pattern_html_tag_a],
            'authors': [compile(r'<span itemprop="author" data-type="author">([\s\S]*?)</span>'), pattern_html_tag_a],
        }

        field_dict = {}
        for fname, pat in patterns.items():
            val = match_field(fname, pat, html)
            if val is None:
                val = ''
            field_dict[fname] = val

        return AlbumStub(**field_dict)


    def format_album_url(aid, domain='18comic.vip') -> str:
        return f'https://{domain}/album/{aid}/'


    def get_album_cover_url(album_id, image_domain=None, size=''):
        if image_domain is None:
            image_domain = 'cdn-msp.jmapiproxy1.cc'
        return f'https://{image_domain}/media/albums/{parse_to_jm_id(album_id)}{size}.jpg'


    
def get_all_image_urls(album_id: str, download: bool = False, save_dir: Optional[str] = None) -> list:
    """
    使用项目的解析与 Postman 来获取所有图片 URL；如果项目不可用，会抛出错误。
    :param album_id: JM 车号
    :param download: 如果为 True，会把图片保存到 save_dir
    :param save_dir: 保存目录（download=True 时必需）
    :return: 图片 URL 列表
    """
    import requests
    if PROJECT_JMCONFIG is None:
        raise RuntimeError('项目源码不可用，无法获取完整图片列表。请确保运行在项目根目录并且 src 可导入。')

    # Use project toolkit
    domain = PROJECT_JMCONFIG.get_html_domain()
    postman = PROJECT_JMCONFIG.new_postman(session=True)
    headers = PROJECT_JMCONFIG.new_html_headers(domain)

    urls = []

    album_url = JmcomicText.format_url(f'/album/{album_id}/', domain)
    resp = postman.get(album_url, headers=headers, timeout=20)
    resp.raise_for_status()
    album = JmcomicText.analyse_jm_album_html(resp.text)

    for pid, pindex, pname in album.episode_list:
        photo_url = JmcomicText.format_url(f'/photo/{pid}/', domain)
        r = postman.get(photo_url, headers=headers, timeout=20)
        r.raise_for_status()
        photo = JmcomicText.analyse_jm_photo_html(r.text)
        photo.from_album = album
        photo.data_original_query_params = photo.get_data_original_query_params(getattr(photo, 'data_original_0', None))

        for i in range(len(photo)):
            img = photo.getindex(i)
            urls.append(img.download_url)

            if download:
                if save_dir is None:
                    raise ValueError('download=True 时必须提供 save_dir')
                from os import makedirs
                makedirs(save_dir, exist_ok=True)
                try:
                    ir = postman.get(img.download_url, headers=PROJECT_JMCONFIG.APP_HEADERS_IMAGE, timeout=30)
                    ir.raise_for_status()
                    # 使用项目的图片工具判断并解密图片
                    from jmcomic.jm_toolkit import JmImageTool

                    # ir.content -> bytes
                    num = JmImageTool.get_num_by_detail(img)
                    if num == 0:
                        path = f"{save_dir}/{img.filename}"
                        with open(path, 'wb') as f:
                            f.write(ir.content)
                    else:
                        # 解密并保存
                        image = JmImageTool.open_image(ir.content)
                        path = f"{save_dir}/{img.filename}"
                        JmImageTool.decode_and_save(num, image, path)
                except Exception:
                    # fallback to plain requests; still try to decode if necessary
                    ir = requests.get(img.download_url, headers=headers, timeout=30)
                    ir.raise_for_status()
                    from jmcomic.jm_toolkit import JmImageTool
                    num = JmImageTool.get_num_by_detail(img)
                    if num == 0:
                        path = f"{save_dir}/{img.filename}"
                        with open(path, 'wb') as f:
                            f.write(ir.content)
                    else:
                        image = JmImageTool.open_image(ir.content)
                        path = f"{save_dir}/{img.filename}"
                        JmImageTool.decode_and_save(num, image, path)

    return urls


def get_all_image_details(album_id: str) -> list:
    """
    返回指定 album 的所有 JmImageDetail 对象（包含 scramble_id、filename、download_url 等），用于 GUI 显示与解密。
    """
    if PROJECT_JMCONFIG is None:
        raise RuntimeError('项目源码不可用，无法获取完整图片详情。')

    domain = PROJECT_JMCONFIG.get_html_domain()
    postman = PROJECT_JMCONFIG.new_postman(session=True)
    headers = PROJECT_JMCONFIG.new_html_headers(domain)

    result = []

    album_url = JmcomicText.format_url(f'/album/{album_id}/', domain)
    resp = postman.get(album_url, headers=headers, timeout=20)
    resp.raise_for_status()
    album = JmcomicText.analyse_jm_album_html(resp.text)

    for pid, pindex, pname in album.episode_list:
        photo_url = JmcomicText.format_url(f'/photo/{pid}/', domain)
        r = postman.get(photo_url, headers=headers, timeout=20)
        r.raise_for_status()
        photo = JmcomicText.analyse_jm_photo_html(r.text)
        photo.from_album = album
        # ensure query params
        photo.data_original_query_params = photo.get_data_original_query_params(getattr(photo, 'data_original_0', None))

        for i in range(len(photo)):
            img = photo.getindex(i)
            result.append(img)

    return result


def decode_image_pil(img_bytes: bytes, num: int):
    """
    根据分割数 num，解密并返回 PIL.Image 对象（不保存到磁盘）。
    num == 0 表示不需要解密，直接返回打开的 Image。
    """
    from io import BytesIO
    from PIL import Image

    img = Image.open(BytesIO(img_bytes)).convert('RGB')

    if num == 0:
        return img

    w, h = img.size

    img_decode = Image.new('RGB', (w, h))
    over = h % num
    import math
    for i in range(num):
        move = math.floor(h / num)
        y_src = h - (move * (i + 1)) - over
        y_dst = move * i

        if i == 0:
            move += over
        else:
            y_dst += over

        box = (0, y_src, w, y_src + move)
        region = img.crop(box)
        img_decode.paste(region, (0, y_dst, w, y_dst + move))

    return img_decode


def search_albums(search_query: str, page: int = 1):
    """
    简单的站内搜索，返回 (album_id, title) 列表。
    """
    if PROJECT_JMCONFIG is None:
        raise RuntimeError('项目源码不可用，无法执行搜索')

    from urllib.parse import urlencode
    domain = PROJECT_JMCONFIG.get_html_domain()
    postman = PROJECT_JMCONFIG.new_postman(session=True)
    headers = PROJECT_JMCONFIG.new_html_headers(domain)

    params = {
        'search_query': search_query,
        'page': page,
    }

    url = PROJECT_JMCONFIG.PROT + domain + '/search/photos?' + urlencode(params)
    resp = postman.get(url, headers=headers, timeout=20)
    resp.raise_for_status()

    # parse search page
    from jmcomic.jm_toolkit import JmPageTool
    page_obj = JmPageTool.parse_html_to_search_page(resp.text)

    results = []
    # page_obj.content holds (album_id, info)
    for aid, info in page_obj.content:
        title = info.get('name', '')
        tags = info.get('tags', [])

        # try fetch album detail page to get authors and category if possible
        authors = []
        category = ''
        try:
            album_url = JmcomicText.format_album_url(aid, domain)
            r = postman.get(album_url, headers=headers, timeout=20)
            r.raise_for_status()
            album = JmcomicText.analyse_jm_album_html(r.text)
            authors = album.authors if hasattr(album, 'authors') else []
            # category may appear in tags or elsewhere; keep tags
        except Exception:
            pass

        results.append((aid, title, authors, tags, category))

    return results
