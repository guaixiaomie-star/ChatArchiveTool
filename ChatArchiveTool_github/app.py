import argparse
import os
import shutil
import socket
import sys
import threading
import webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from extractors.openai_web import OpenAIWebExtractor
from extractors.chatbox_extractor import ChatboxExtractor
from extractors.cherry_extractor import CherryExtractor
from extractors.rikka_extractor import RikkaExtractor
from core.packer import pack_archive, save_archive


def resource_path(relative_path: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


def copy_viewer_to_output(output_dir: str) -> str:
    viewer_src = resource_path("viewer")
    viewer_dst = os.path.join(output_dir, "viewer")

    if not os.path.exists(viewer_src):
        raise FileNotFoundError(f"找不到 viewer 目录: {viewer_src}")

    if os.path.exists(viewer_dst):
        shutil.rmtree(viewer_dst)

    shutil.copytree(viewer_src, viewer_dst)

    # 再复制 archive.json 到 viewer 同级，方便 index.html fetch
    archive_src = os.path.join(output_dir, "archive.json")
    archive_dst = os.path.join(viewer_dst, "archive.json")
    if os.path.exists(archive_src):
        shutil.copy2(archive_src, archive_dst)

    return viewer_dst


def find_free_port(start: int = 8000, end: int = 8999) -> int:
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("没有找到可用端口")


def start_static_server(directory: str, port: int):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=directory, **kwargs)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def main():
    parser = argparse.ArgumentParser(description="通用聊天记录提取工具（全模型）")
    parser.add_argument("--openai", help="OpenAI 官网导出 JSON 文件路径")
    parser.add_argument("--chatbox", help="Chatbox 导出 JSON 文件路径")
    parser.add_argument("--cherry", help="Cherry Studio 导出 JSON 文件路径")
    parser.add_argument("--rikka-db", help="RikkaHub 的 SQLite 数据库路径")
    parser.add_argument("--rikka-upload", help="RikkaHub upload 图片目录路径")
    parser.add_argument("--output", default="output", help="输出目录")
    parser.add_argument("--no-browser", action="store_true", help="仅生成文件，不自动打开浏览器")
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)

    sessions = []

    if args.openai:
        sessions.extend(OpenAIWebExtractor().extract(args.openai, args.output))

    if args.chatbox:
        sessions.extend(ChatboxExtractor().extract(args.chatbox, args.output))

    if args.cherry:
        sessions.extend(CherryExtractor().extract(args.cherry, args.output))

    if args.rikka_db:
        sessions.extend(RikkaExtractor(upload_dir=args.rikka_upload).extract(args.rikka_db, args.output))

    sessions.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

    archive = pack_archive(sessions)
    archive_path = save_archive(archive, args.output)

    print(f"✅ 已生成通用档案：{archive_path}")
    print(f"📦 共提取 {len(sessions)} 个会话")

    viewer_dir = copy_viewer_to_output(args.output)
    print(f"🖼️ 已复制查看器到：{viewer_dir}")

    if not args.no_browser:
        port = find_free_port()
        server = start_static_server(viewer_dir, port)
        url = f"http://127.0.0.1:{port}/index.html"
        print(f"🌐 正在打开：{url}")
        webbrowser.open(url)

        try:
            input("按回车键关闭本地查看服务...\n")
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()