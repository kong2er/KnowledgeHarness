"""HTTP-level smoke tests for service/simple_ui.py.

Run:
    python3 tests/test_simple_ui.py
"""

from __future__ import annotations

import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import service.simple_ui as su  # noqa: E402

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


def _start_server() -> tuple[object, str]:
    server = su.create_server("127.0.0.1", 0, auto_fallback=False)
    host, port = server.server_address[:2]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://{host}:{port}"


def _request(
    method: str,
    url: str,
    data: bytes | None = None,
    headers: Dict[str, str] | None = None,
) -> tuple[int, str, Dict[str, str]]:
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)

    last_err: Exception | None = None
    for _ in range(20):
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = resp.read().decode("utf-8", "replace")
                return int(resp.status), body, dict(resp.headers.items())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            return int(exc.code), body, dict(exc.headers.items())
        except urllib.error.URLError as exc:
            last_err = exc
            time.sleep(0.05)
    raise RuntimeError(f"request failed after retries: {last_err}")


def _encode_multipart(
    fields: Dict[str, str],
    files: Iterable[Tuple[str, str, bytes, str]],
) -> tuple[str, bytes]:
    boundary = "----KnowledgeHarnessBoundary7MA4YWxkTrZu0gW"
    lines: List[bytes] = []

    for name, value in fields.items():
        lines.append(f"--{boundary}".encode("utf-8"))
        lines.append(
            f'Content-Disposition: form-data; name="{name}"'.encode("utf-8")
        )
        lines.append(b"")
        lines.append(str(value).encode("utf-8"))

    for field, filename, content, content_type in files:
        lines.append(f"--{boundary}".encode("utf-8"))
        lines.append(
            (
                f'Content-Disposition: form-data; name="{field}"; '
                f'filename="{filename}"'
            ).encode("utf-8")
        )
        lines.append(f"Content-Type: {content_type}".encode("utf-8"))
        lines.append(b"")
        lines.append(content)

    lines.append(f"--{boundary}--".encode("utf-8"))
    lines.append(b"")
    body = b"\r\n".join(lines)
    return f"multipart/form-data; boundary={boundary}", body


def test_settings_key_masking() -> None:
    print("[test] settings key masking")
    old_env_path = su.ENV_PATH
    secret = "sk-ui-secret-123456"
    server = None
    try:
        with tempfile.TemporaryDirectory() as d:
            su.ENV_PATH = Path(d) / ".env"
            su.ENV_PATH.write_text(
                "\n".join(
                    [
                        "KNOWLEDGEHARNESS_API_URL=https://api.example.com",
                        f"KNOWLEDGEHARNESS_API_KEY={secret}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            server, base = _start_server()
            status, body, _ = _request("GET", f"{base}/settings")
    except PermissionError:
        print("  SKIP: socket bind not permitted in current environment")
        return
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        su.ENV_PATH = old_env_path

    _check("settings status 200", status == 200, str(status))
    _check(
        "password input attrs",
        ('type="password"' in body) and ('autocomplete="new-password"' in body),
        body[:300],
    )
    _check("secret not echoed in html", secret not in body, "api key leaked")


def test_download_whitelist() -> None:
    print("[test] download whitelist")
    test_file = su.OUTPUT_WHITELIST_ROOT / "_ui_download_test.md"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("download-ok\n", encoding="utf-8")

    server = None
    try:
        server, base = _start_server()
        status_ok, body_ok, headers_ok = _request(
            "GET", f"{base}/download?name={urllib.parse.quote(test_file.name)}"
        )
        status_bad1, _body_bad1, _ = _request(
            "GET", f"{base}/download?name=../README.md"
        )
        status_bad2, _body_bad2, _ = _request(
            "GET", f"{base}/download?name=subdir%2Fdemo.md"
        )
    except PermissionError:
        print("  SKIP: socket bind not permitted in current environment")
        return
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        try:
            test_file.unlink()
        except OSError:
            pass

    _check("download allowed basename 200", status_ok == 200, str(status_ok))
    _check("download content ok", "download-ok" in body_ok, body_ok[:120])
    _check(
        "download attachment header",
        "attachment" in (headers_ok.get("Content-Disposition", "") or ""),
        str(headers_ok),
    )
    _check("download blocks traversal", status_bad1 == 400, str(status_bad1))
    _check("download blocks subdir", status_bad2 == 400, str(status_bad2))


def test_run_input_errors_and_limits() -> None:
    print("[test] run input errors + upload limit")
    su._clear_upload_pool()
    server = None
    try:
        server, base = _start_server()

        # 1) Empty selection should be 400 input error.
        payload = urllib.parse.urlencode({"ui_mode": "prod"}).encode("utf-8")
        status_empty, body_empty, _ = _request(
            "POST",
            f"{base}/run",
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        # 2) Too many images should be 400 before pipeline execution.
        files = [
            ("upload_files", f"img_{i}.png", b"123", "image/png")
            for i in range(su.MAX_IMAGE_COUNT_PER_RUN + 1)
        ]
        ctype, body = _encode_multipart({"ui_mode": "prod"}, files)
        status_limit, body_limit, _ = _request(
            "POST",
            f"{base}/run",
            data=body,
            headers={"Content-Type": ctype},
        )
    except PermissionError:
        print("  SKIP: socket bind not permitted in current environment")
        return
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        su._clear_upload_pool()

    _check("empty run -> 400", status_empty == 400, str(status_empty))
    _check("empty run has input error", "输入错误" in body_empty, body_empty[:180])
    _check("image limit -> 400", status_limit == 400, str(status_limit))
    _check("image limit message", "图片文件过多" in body_limit, body_limit[:220])


def test_run_pipeline_error_is_500() -> None:
    print("[test] run pipeline exception -> 500")
    su._clear_upload_pool()
    old_run_pipeline = su.run_pipeline
    server = None
    try:
        def _boom(*args, **kwargs):
            raise RuntimeError("boom-test")

        su.run_pipeline = _boom
        server, base = _start_server()

        ctype, body = _encode_multipart(
            {"ui_mode": "prod", "output_dir": "outputs"},
            [("upload_files", "demo.md", "概念：测试".encode("utf-8"), "text/markdown")],
        )
        status, html_body, _ = _request(
            "POST",
            f"{base}/run",
            data=body,
            headers={"Content-Type": ctype},
        )
    except PermissionError:
        print("  SKIP: socket bind not permitted in current environment")
        return
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        su.run_pipeline = old_run_pipeline
        su._clear_upload_pool()

    _check("pipeline error -> 500", status == 500, str(status))
    _check("500 body keeps UI", "流水线异常" in html_body, html_body[:200])


def main() -> None:
    print("=" * 60)
    print("simple_ui HTTP tests")
    print("=" * 60)
    # quick preflight: skip all tests if sockets are forbidden.
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.close()
    except PermissionError:
        print("SKIP: socket bind not permitted in current environment")
        print("Result: 0 passed, 0 failed")
        raise SystemExit(0)

    test_settings_key_masking()
    test_download_whitelist()
    test_run_input_errors_and_limits()
    test_run_pipeline_error_is_500()

    print("-" * 60)
    print(f"Result: {_passed} passed, {_failed} failed")
    raise SystemExit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
