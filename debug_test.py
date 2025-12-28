"""非 GUI 测试脚本：请求并解析 ID=1212975，打印调试信息到控制台。"""
import requests
from jm_api import parse_to_jm_id, format_album_url, analyse_jm_album_html, get_album_cover_url, PROJECT_JMCONFIG

ID = '1212975'

print('开始 Debug 测试: ID=', ID)
try:
    aid = parse_to_jm_id(ID)
    print('parse_to_jm_id ->', aid)

    postman = None
    if PROJECT_JMCONFIG is not None:
        try:
            domain = PROJECT_JMCONFIG.get_html_domain()
            print('PROJECT_JMCONFIG.get_html_domain ->', domain)
            url = format_album_url(aid, domain)
            print('format_album_url ->', url)
            headers = PROJECT_JMCONFIG.new_html_headers(domain)
            postman = PROJECT_JMCONFIG.new_postman(session=True)
            print('使用项目 Postman 请求详情页')
            resp = postman.get(url, headers=headers, timeout=20)
        except Exception as e:
            print('项目 Postman 请求失败 ->', e)
            postman = None

    if postman is None:
        url = format_album_url(aid)
        print('format_album_url ->', url)
        headers = {'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9', 'user-agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=20)
    print('HTTP status:', resp.status_code)
    resp.raise_for_status()

    album = analyse_jm_album_html(resp.text)
    print('Album title:', getattr(album, 'name', ''))
    print('Album authors:', getattr(album, 'authors', ''))
    print('Album page_count:', getattr(album, 'page_count', ''))

    cover = get_album_cover_url(aid)
    print('cover_url ->', cover)
    # try fetch cover head
    if postman is not None:
        try:
            img_headers = PROJECT_JMCONFIG.new_html_headers(domain)
            r2 = postman.get(cover, headers=img_headers, timeout=15)
        except Exception as e:
            print('postman get cover failed ->', e)
            r2 = requests.get(cover, headers=headers, timeout=15)
    else:
        r2 = requests.get(cover, headers=headers, timeout=15)
    print('cover http status:', r2.status_code, 'len:', len(r2.content))

except Exception as e:
    print('ERROR:', e)
