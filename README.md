轻量版 JMComic Crawler - Lite

说明：
- 本目录包含一个独立的轻量 GUI 应用，内含最小依赖：requests, Pillow
- GUI 与实现模块分离：
  - `app_gui.py` - tkinter GUI
  - `jm_api.py` - 使用项目中的解析逻辑（复制必要函数），用于获取本子详情与封面

运行：
1. 在虚拟环境中安装依赖：
   pip install -r requirements.txt
2. 运行 GUI：
   python app_gui.py
