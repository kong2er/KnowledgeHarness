"""UI server bind fallback tests.

Run:
    python3 tests/test_ui_server_port_fallback.py
"""

from __future__ import annotations

import errno
import socket
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from service.simple_ui import create_server  # noqa: E402


_passed = 0
_failed = 0


def _check(name: str, cond: bool, detail: str = "") -> None:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS: {name}")
    else:
        _failed += 1
        print(f"  FAIL: {name} -- {detail}")


def _reserve_port(host: str = "127.0.0.1") -> tuple[socket.socket, int]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, 0))
    sock.listen(1)
    return sock, int(sock.getsockname()[1])


def test_create_server_fallback() -> None:
    print("[test] create_server fallback")
    try:
        blocker, busy_port = _reserve_port()
    except PermissionError:
        print("  SKIP: socket bind not permitted in current environment")
        return
    server = None
    try:
        server = create_server(
            "127.0.0.1",
            busy_port,
            auto_fallback=True,
            max_port_tries=10,
        )
        bound_port = int(server.server_address[1])
        _check(
            "fallback picked another port",
            bound_port != busy_port,
            f"bound_port={bound_port}, busy_port={busy_port}",
        )
    finally:
        if server is not None:
            server.server_close()
        blocker.close()


def test_create_server_no_fallback_raises() -> None:
    print("[test] create_server no-fallback raises")
    try:
        blocker, busy_port = _reserve_port()
    except PermissionError:
        print("  SKIP: socket bind not permitted in current environment")
        return
    try:
        try:
            create_server(
                "127.0.0.1",
                busy_port,
                auto_fallback=False,
            )
        except OSError as exc:
            _check(
                "raise EADDRINUSE",
                exc.errno == errno.EADDRINUSE,
                f"errno={exc.errno}",
            )
        else:
            _check("raise EADDRINUSE", False, "expected OSError, got no exception")
    finally:
        blocker.close()


def main() -> None:
    print("=" * 60)
    print("UI server port fallback tests")
    print("=" * 60)
    test_create_server_fallback()
    test_create_server_no_fallback_raises()
    print("-" * 60)
    print(f"Result: {_passed} passed, {_failed} failed")
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
