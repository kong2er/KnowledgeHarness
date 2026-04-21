"""Minimal check for Flask service entry.

Same structure as tests/test_api_service_entry.py (FastAPI probe).
Run: python3 tests/test_flask_service_entry.py
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _print_head(title: str) -> None:
    print("=" * 60)
    print(title)
    print("=" * 60)


def test_service_module_import() -> tuple[bool, str]:
    try:
        flask = importlib.import_module("flask")
        assert flask is not None
    except Exception:
        return True, "SKIP: flask not installed"

    module = importlib.import_module("service.flask_server")
    if not hasattr(module, "app"):
        return False, "service.flask_server missing app"

    # Assert the three required endpoints are registered on the app.
    rules = {r.rule: sorted(r.methods - {"HEAD", "OPTIONS"}) for r in module.app.url_map.iter_rules()}
    required = {
        "/health": ["GET"],
        "/pipeline/run": ["POST"],
        "/pipeline/capabilities": ["GET"],
    }
    for path, methods in required.items():
        if path not in rules:
            return False, f"missing route {path}"
        if rules[path] != methods:
            return False, f"route {path} methods {rules[path]} != {methods}"

    return True, "PASS: service entry app + 3 routes exist"


def test_pipeline_request_parser() -> tuple[bool, str]:
    """Exercise the stdlib parser without needing flask installed."""
    try:
        flask = importlib.import_module("flask")
        assert flask is not None
    except Exception:
        return True, "SKIP: flask not installed"

    module = importlib.import_module("service.flask_server")
    parse = module._parse_pipeline_request

    # Happy path: inputs list is accepted, other fields default.
    ok = parse({"inputs": ["samples/demo.md"]})
    if ok["output_dir"] != "outputs":
        return False, "default output_dir not applied"
    if ok["topic_mode"] is not None:
        return False, "default topic_mode should be None (inherit runtime config)"

    # Rejection paths.
    for bad, reason in [
        (None, "non-dict body"),
        ([], "list body"),
        ({}, "missing inputs"),
        ({"inputs": []}, "empty inputs"),
        ({"inputs": ["", " "]}, "blank string inputs"),
        ({"inputs": "samples/demo.md"}, "string inputs"),
    ]:
        try:
            parse(bad)
        except ValueError:
            continue
        return False, f"parser accepted bad input: {reason}"

    # Numeric coercion
    coerced = parse(
        {
            "inputs": ["x"],
            "topic_api_timeout": "7.5",
            "keypoint_max_points": "20",
            "enable_web_enrichment": 1,
        }
    )
    if coerced["topic_api_timeout"] != 7.5:
        return False, "timeout not coerced to float"
    if coerced["keypoint_max_points"] != 20:
        return False, "max_points not coerced to int"
    if coerced["enable_web_enrichment"] is not True:
        return False, "enable flag not coerced to bool"

    parsed_bool = parse({"inputs": ["x"], "enable_api_assist": "false"})
    if parsed_bool["enable_api_assist"] is not False:
        return False, "string false should coerce to bool False"
    parsed_profile = parse({"inputs": ["x"], "validation_profile": "lenient"})
    if parsed_profile["validation_profile"] != "lenient":
        return False, "validation_profile not preserved"

    return True, "PASS: parser accepts/rejects correctly"


def test_health_and_capabilities_endpoints() -> tuple[bool, str]:
    """Exercise /health and /pipeline/capabilities via Flask test client."""
    try:
        flask = importlib.import_module("flask")
        assert flask is not None
    except Exception:
        return True, "SKIP: flask not installed"

    module = importlib.import_module("service.flask_server")
    client = module.app.test_client()

    r = client.get("/health")
    if r.status_code != 200:
        return False, f"/health returned {r.status_code}"
    body = r.get_json()
    if body.get("status") != "ok":
        return False, f"/health payload unexpected: {body}"
    if "features" not in body or "topic_api_configured" not in body["features"]:
        return False, "/health missing feature flags"
    if "image_ocr_api_configured" not in body["features"]:
        return False, "/health missing image_ocr_api_configured flag"

    r = client.get("/pipeline/capabilities")
    if r.status_code != 200:
        return False, f"/pipeline/capabilities returned {r.status_code}"
    body = r.get_json()
    if body.get("framework") != "flask":
        return False, "/pipeline/capabilities missing framework marker"

    return True, "PASS: /health + /pipeline/capabilities both 200"


def test_pipeline_run_rejects_bad_body() -> tuple[bool, str]:
    """Exercise the 400 path: non-JSON and empty inputs should NOT crash."""
    try:
        flask = importlib.import_module("flask")
        assert flask is not None
    except Exception:
        return True, "SKIP: flask not installed"

    module = importlib.import_module("service.flask_server")
    client = module.app.test_client()

    # Empty inputs list → 400 validation error.
    r = client.post("/pipeline/run", json={"inputs": []})
    if r.status_code != 400:
        return False, f"empty-inputs should return 400, got {r.status_code}"

    # Non-existent file list → still 400 (collect_input_files returns empty).
    r = client.post("/pipeline/run", json={"inputs": ["/nonexistent/x.md"]})
    if r.status_code != 400:
        return False, f"no-valid-inputs should return 400, got {r.status_code}"

    return True, "PASS: /pipeline/run validates inputs and returns 400"


if __name__ == "__main__":
    _print_head("Flask service entry tests")

    cases = [
        ("service module + 3 routes", test_service_module_import),
        ("request parser accept/reject", test_pipeline_request_parser),
        ("health + capabilities endpoints", test_health_and_capabilities_endpoints),
        ("pipeline/run validates bad body", test_pipeline_run_rejects_bad_body),
    ]
    passed = 0
    failed = 0
    for name, fn in cases:
        ok, msg = fn()
        print(f"[test] {name}")
        print(f"  {msg}")
        if ok:
            passed += 1
        else:
            failed += 1

    print("-" * 60)
    print(f"Result: {passed} passed, {failed} failed")
    if failed:
        raise SystemExit(1)
