"""Minimal stdlib-only tests for topic_coarse_classify.

Run directly:

    python3 tests/test_topic_coarse_classify.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import tools.topic_coarse_classify as tc  # noqa: E402

_passed = 0
_failed = 0


def _check(name, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS: {name}")
    else:
        _failed += 1
        print(f"  FAIL: {name} -- {detail}")


def _doc(text: str):
    return {
        "source_name": "x.md",
        "source_path": "/tmp/x.md",
        "source_type": "md",
        "extracted_text": text,
    }


def test_local_mode_basic():
    print("[test] local mode basic")
    out = tc.topic_coarse_classify([_doc("线性代数与概率论复习")], mode="local")
    item = out["items"][0]
    _check("label in allowed", item["topic_label"] in out["allowed_labels"], str(item))
    _check("no api used", item["used_api"] is False, str(item))


def test_unknown_topic_on_no_hint():
    print("[test] unknown when no hint")
    out = tc.topic_coarse_classify([_doc("这是一段无明显学科标签的文本")], mode="local")
    item = out["items"][0]
    _check("unknown label", item["topic_label"] == "unknown_topic", str(item))


def test_api_out_of_scope_fallbacks_to_local():
    print("[test] api out-of-scope falls back")

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {"topic_label": "new_topic_not_allowed", "confidence": 0.99, "reason": "api"}
            ).encode("utf-8")

    old_urlopen = tc.request.urlopen
    old_url = os.environ.get("TOPIC_CLASSIFIER_API_URL")
    os.environ["TOPIC_CLASSIFIER_API_URL"] = "http://fake.local/topic"
    tc.request.urlopen = lambda req, timeout=0: FakeResp()  # noqa: E731
    try:
        out = tc.topic_coarse_classify([_doc("软件工程课程")], mode="api")
    finally:
        tc.request.urlopen = old_urlopen
        if old_url is None:
            os.environ.pop("TOPIC_CLASSIFIER_API_URL", None)
        else:
            os.environ["TOPIC_CLASSIFIER_API_URL"] = old_url

    item = out["items"][0]
    _check("fallback state api_to_local", item["fallback_state"] == "api_to_local", str(item))
    _check("label constrained", item["topic_label"] in out["allowed_labels"], str(item))
    _check("warnings present", len(out["warnings"]) >= 1, str(out["warnings"]))


def test_api_exception_fallbacks():
    print("[test] api exception fallback")

    def raise_url_error(req, timeout=0):
        raise tc.error.URLError("timeout")

    old_urlopen = tc.request.urlopen
    old_url = os.environ.get("TOPIC_CLASSIFIER_API_URL")
    os.environ["TOPIC_CLASSIFIER_API_URL"] = "http://fake.local/topic"
    tc.request.urlopen = raise_url_error
    try:
        out = tc.topic_coarse_classify([_doc("deep learning transformer")], mode="api")
    finally:
        tc.request.urlopen = old_urlopen
        if old_url is None:
            os.environ.pop("TOPIC_CLASSIFIER_API_URL", None)
        else:
            os.environ["TOPIC_CLASSIFIER_API_URL"] = old_url

    item = out["items"][0]
    _check("fallback marked", item["fallback_state"] == "api_to_local", str(item))
    _check("no crash output present", "topic_label" in item, str(item))


def test_taxonomy_auto_appends_unknown():
    print("[test] taxonomy auto-append unknown")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "taxonomy.json"
        p.write_text(
            json.dumps(
                {
                    "labels": [
                        {
                            "label_id": "software_engineering",
                            "display_name": "Software Engineering",
                            "aliases": ["软件工程"],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        out = tc.topic_coarse_classify([_doc("无关文本")], taxonomy_path=str(p), mode="local")
    _check("unknown appended", "unknown_topic" in out["allowed_labels"], str(out["allowed_labels"]))


def test_openai_compatible_topic_api():
    print("[test] openai-compatible topic api")

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            payload = {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "topic_label": "software_engineering",
                                    "confidence": 0.88,
                                    "reason": "matched software topic",
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }
            return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    captured = {"url": ""}

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        return FakeResp()

    old_urlopen = tc.request.urlopen
    old_url = os.environ.get("TOPIC_CLASSIFIER_API_URL")
    old_style = os.environ.get("TOPIC_CLASSIFIER_API_STYLE")
    os.environ["TOPIC_CLASSIFIER_API_URL"] = "https://api.deepseek.com"
    os.environ["TOPIC_CLASSIFIER_API_STYLE"] = "openai_compatible"
    tc.request.urlopen = fake_urlopen
    try:
        out = tc.topic_coarse_classify([_doc("软件工程设计模式")], mode="api")
    finally:
        tc.request.urlopen = old_urlopen
        if old_url is None:
            os.environ.pop("TOPIC_CLASSIFIER_API_URL", None)
        else:
            os.environ["TOPIC_CLASSIFIER_API_URL"] = old_url
        if old_style is None:
            os.environ.pop("TOPIC_CLASSIFIER_API_STYLE", None)
        else:
            os.environ["TOPIC_CLASSIFIER_API_STYLE"] = old_style

    item = out["items"][0]
    _check("openai mode api used", item["used_api"] is True, str(item))
    _check("label parsed", item["topic_label"] == "software_engineering", str(item))
    _check(
        "endpoint auto completed",
        captured["url"].endswith("/v1/chat/completions"),
        captured["url"],
    )


def main():
    print("=" * 60)
    print("Topic coarse classifier: minimal tests")
    print("=" * 60)
    test_local_mode_basic()
    test_unknown_topic_on_no_hint()
    test_api_out_of_scope_fallbacks_to_local()
    test_api_exception_fallbacks()
    test_taxonomy_auto_appends_unknown()
    test_openai_compatible_topic_api()
    print("-" * 60)
    print(f"Result: {_passed} passed, {_failed} failed")
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
