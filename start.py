#!/usr/bin/env python3
"""
Claude-Hermes Bridge 启动器（FastAPI 版本）
直接双击运行此文件即可启动
"""

import os
import sys
import subprocess
import webbrowser
import time

BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    print("🚀 启动 Claude-Hermes Bridge (FastAPI)...")
    print(f"📁 目录: {BRIDGE_DIR}")
    print("")

    # 检查 server_fastapi.py 是否存在
    server_fastapi = os.path.join(BRIDGE_DIR, "server_fastapi.py")
    if not os.path.exists(server_fastapi):
        print(f"❌ 找不到 server_fastapi.py")
        input("按回车键退出...")
        return

    # 启动 FastAPI 服务器
    print("📦 启动 FastAPI 服务器 (uvicorn)...")
    print("")

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server_fastapi:app", "--host", "0.0.0.0", "--port", "8765"],
        cwd=BRIDGE_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # 等待服务器启动
    time.sleep(3)

    # 打开浏览器
    print("🌐 打开浏览器...")
    webbrowser.open("http://localhost:8765")

    print("")
    print("=" * 50)
    print("✅ 服务已启动!")
    print("🌐 访问地址: http://localhost:8765")
    print("📖 API 文档:  http://localhost:8765/docs")
    print("")
    print("按 Ctrl+C 停止服务")
    print("=" * 50)

    # 等待进程退出
    try:
        proc.wait()
    except KeyboardInterrupt:
        print("\n👋 正在停止服务...")
        proc.terminate()
        proc.wait()
        print("✅ 服务已停止")


if __name__ == "__main__":
    main()
