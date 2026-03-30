# ChatArchiveTool

本地离线的聊天记录提取与查看工具。  
支持从多个平台导出聊天记录，整理为统一档案，并自动在浏览器中打开查看页面。

## 支持平台

- OpenAI 官网
- Chatbox
- Cherry Studio
- RikkaHub

## 功能特点

- 本地离线运行
- 支持多平台聊天记录提取
- 自动生成统一格式的 `archive.json`
- 自动复制网页查看器
- 自动打开浏览器查看聊天记录
- 支持图片展示
- 支持多平台合并浏览

## 项目结构

core/
extractors/
viewer/
app.py
requirements.txt

## 运行环境
Python 3.11 或更高版本（推荐）
Windows

## 安装依赖
pip install -r requirements.txt

## 运行示例
1. 只导入 Chatbox
python app.py --chatbox chatbox.json --output output
2. 只导入 OpenAI 官网
python app.py --openai openai.json --output output
3. 只导入 Cherry Studio
python app.py --cherry cherry.json --output output
4. 只导入 RikkaHub
python app.py --rikka-db rikka_hub.db --rikka-upload upload --output output
5. 同时导入多个平台
python app.py --openai openai.json --chatbox chatbox.json --cherry cherry.json --rikka-db rikka_hub.db --rikka-upload upload --output output

## 参数说明
--openai
OpenAI 官网导出的 JSON 文件路径
--chatbox
Chatbox 导出的 JSON 文件路径
--cherry
Cherry Studio 导出的 JSON 文件路径
--rikka-db
RikkaHub 的 SQLite 数据库路径
--rikka-upload
RikkaHub 的 upload 图片目录路径
--output
输出目录，默认是 output
--no-browser
只生成档案文件，不自动打开浏览器

## 输出结果
程序运行成功后会自动生成：
output/archive.json
output/viewer/
并自动打开浏览器查看聊天记录。

## 打包
本项目可以使用 PyInstaller 打包：
python -m PyInstaller --name ChatArchiveTool --onedir --add-data "viewer;viewer" app.py
打包完成后，可执行文件位于：
dist/ChatArchiveTool/
注意：--onedir 模式下，必须保留整个 ChatArchiveTool 文件夹，不能只单独保留 ChatArchiveTool.exe。

## 下载成品
成品包请前往 GitHub Releases 下载。

## 隐私说明
本工具在本地离线运行，不会自动上传聊天记录到服务器。
请在分享导出文件、archive.json 或截图前自行检查内容。

## 注意事项
请不要把自己的聊天记录文件上传到公开仓库
请不要把 output/、dist/、build/ 里的内容直接提交到源码仓库
RikkaHub 如果需要显示图片，请同时提供 upload 文件夹
浏览器页面读取的是本地生成的 archive.json
