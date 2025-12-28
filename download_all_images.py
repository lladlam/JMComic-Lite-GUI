"""
示例脚本：列出并下载指定 album 的所有图片（默认 ID=1212975）
用法：修改下面的 ALBUM_ID 和 SAVE_DIR 后运行
"""
from jm_api import get_all_image_urls

ALBUM_ID = '1212975'
SAVE_DIR = 'downloads_1212975'

if __name__ == '__main__':
    urls = get_all_image_urls(ALBUM_ID, download=True, save_dir=SAVE_DIR)
    print('总图片数:', len(urls))
    for u in urls:
        print(u)
