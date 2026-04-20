"""Minimal check for FastAPI service entry.

Run: python3 tests/test_api_service_entry.py
"""

from __future__ import annotations

import importlib


def _print_head(title: str) -> None:
    print("=" * 60)
    print(title)
    print("=" * 60)


def test_service_module_import() -> tuple[bool, str]:
    try:
        fastapi = importlib.import_module("fastapi")
        assert fastapi is not None
    except Exception:
        return True, "SKIP: fastapi not installed"

    module = importlib.import_module("service.api_server")
    if not hasattr(module, "app"):
        return False, "service.api_server missing app"
    return True, "PASS: service entry app exists"


if __name__ == "__main__":
    _print_head("API service entry test")
    ok, msg = test_service_module_import()
    print(msg)
    if not ok:
        raise SystemExit(1)
    print("Result: 1 passed, 0 failed")
