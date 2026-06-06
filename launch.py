"""行业投资日历系统 — 一键启动脚本"""

import os
import sys
import time
import subprocess
import webbrowser
import socket
import http.client

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PORT = 5000
HOST = f"http://localhost:{PORT}"


def check_port(port):
    """检查端口是否已被占用"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def kill_port(port):
    """杀掉占用端口的进程（Windows）"""
    try:
        result = subprocess.run(
            f'netstat -ano | findstr ":{port} " | findstr LISTENING',
            shell=True, capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.strip().split("\n"):
            parts = line.strip().split()
            if parts:
                pid = parts[-1]
                subprocess.run(f"taskkill /F /PID {pid}",
                               shell=True, capture_output=True, timeout=5)
                print(f"  [OK] 已清理旧进程 PID={pid}")
    except Exception:
        pass


def wait_for_server(url, timeout=20):
    """等待服务器就绪"""
    for i in range(timeout):
        try:
            conn = http.client.HTTPConnection("localhost", PORT, timeout=2)
            conn.request("GET", "/")
            resp = conn.getresponse()
            if resp.status == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def main():
    print("=" * 50)
    print("  行业投资日历系统 — 启动中...")
    print("=" * 50)
    print()

    # 1. Check Python
    print("[..] 检查环境...")
    print(f"  Python {sys.version.split()[0]}")

    # 2. Install deps if needed
    try:
        import flask  # noqa
        import yaml   # noqa
        print("  Flask + PyYAML 已就绪")
    except ImportError:
        print("  [..] 安装依赖中...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "flask", "pyyaml", "-q"],
            shell=True, timeout=60
        )
        print("  [OK] 依赖安装完成")

    # 3. Kill old server
    print("[..] 清理旧进程...")
    kill_port(PORT)
    time.sleep(1)

    # 4. Start server
    print("[..] 启动服务...")
    app_path = os.path.join(BASE_DIR, "web", "app.py")
    log_path = os.path.join(BASE_DIR, "server.log")
    with open(log_path, "w", encoding="utf-8") as log_f:
        server_process = subprocess.Popen(
            [sys.executable, app_path],
            cwd=BASE_DIR,
            stdout=log_f,
            stderr=log_f,
        )

    # 5. Wait for ready
    print("[..] 等待服务就绪...")
    if wait_for_server(HOST):
        print("  [OK] 服务就绪")
    else:
        print("  [..] 服务启动较慢，继续尝试...")

    # 6. Open browser
    print()
    print("=" * 50)
    print("  服务已启动！")
    print()
    print(f"  >> http://localhost:{PORT}")
    print()
    print("  正在打开浏览器...")
    print("  如果未自动跳转，请手动复制上方地址")
    print()
    print("  关闭此窗口 = 停止服务")
    print("=" * 50)
    print()

    webbrowser.open(HOST)

    # 7. Keep running
    try:
        while True:
            time.sleep(5)
            if server_process.poll() is not None:
                print("[信息] 服务已停止")
                break
    except KeyboardInterrupt:
        print("\n[信息] 用户中断")
    finally:
        server_process.terminate()
        server_process.wait(timeout=5)
        print("[信息] 服务已关闭")
        time.sleep(1)


if __name__ == "__main__":
    main()
