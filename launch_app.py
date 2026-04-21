"""Desktop launcher for KnowledgeHarness.

Double-click or run this file to start the local UI and open the browser.
"""

from __future__ import annotations

import argparse
import socket
import threading
import time
import webbrowser

from service.simple_ui import _load_local_env, create_server


def _find_free_port(host: str, start_port: int, max_tries: int = 30) -> int:
    for p in range(start_port, start_port + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, p))
                return p
            except OSError:
                continue
    raise RuntimeError(
        f"No free port found in range [{start_port}, {start_port + max_tries - 1}]"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="KnowledgeHarness 一键启动器")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", default=8765, type=int, help="起始端口")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="仅启动服务，不自动打开浏览器",
    )
    args = parser.parse_args()

    _load_local_env(".env")
    host = args.host
    port = _find_free_port(host, int(args.port))

    server = create_server(host, port)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    url = f"http://{host}:{port}"
    print(f"KnowledgeHarness 已启动：{url}")
    print("按 Ctrl+C 退出")

    if not args.no_browser:
        time.sleep(0.4)
        webbrowser.open(url)

    try:
        while t.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
