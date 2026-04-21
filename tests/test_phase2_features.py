"""Phase-2 feature tests (stdlib-only).

Run directly:

    python3 tests/test_phase2_features.py
"""

from __future__ import annotations

import json
import os
import sys

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app import run_pipeline  # noqa: E402
from tools.classify_notes import classify_notes  # noqa: E402
from tools.detect_semantic_conflicts import detect_semantic_conflicts  # noqa: E402
from tools.stage_summarize import stage_summarize  # noqa: E402
from tools.topic_coarse_classify import topic_coarse_classify  # noqa: E402
from tools.validate_result import validate_result  # noqa: E402
from tools.web_enrichment import web_enrich  # noqa: E402
import tools.classify_notes as cn  # noqa: E402
import tools.stage_summarize as ss  # noqa: E402
import tools.topic_coarse_classify as tc  # noqa: E402
import tools.web_enrichment as we  # noqa: E402

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


def test_web_enrichment_local_extracts_urls():
    print("[test] web enrichment local")
    docs = [
        {
            "source_name": "d.md",
            "extracted_text": (
                "参考链接 https://example.com/a), "
                "以及 [https://openai.com/research]."
            ),
        }
    ]
    out = web_enrich(docs, enabled=True, mode="local", max_items=5)
    resources = out["resources"]
    _check("mode local", out["mode_effective"] == "local", str(out))
    _check("at least one url", len(resources) >= 1, str(resources))
    if resources:
        r = resources[0]
        _check("schema title", "title" in r and bool(r["title"]), str(r))
        _check("schema url", "url" in r and bool(r["url"]), str(r))
        _check("schema purpose", "purpose" in r and bool(r["purpose"]), str(r))
        _check("schema relevance", "relevance_reason" in r and bool(r["relevance_reason"]), str(r))
        _check(
            "url punctuation trimmed",
            all(not item["url"].endswith((")", "]", ".", ",")) for item in resources),
            str(resources),
        )


def test_validate_web_resource_link_check_only_when_enabled():
    print("[test] validate web resource checks")
    cls = {
        "chunks": [],
        "categorized": {
            "basic_concepts": [],
            "methods_and_processes": [],
            "examples_and_applications": [],
            "difficult_or_error_prone_points": [],
            "extended_reading": [],
            "unclassified": [],
        },
    }
    stages = {"stage_1": {}, "stage_2": {}, "stage_3": {}}
    bad_resources = [{"title": "x", "url": "", "purpose": "p", "relevance_reason": ""}]

    out_disabled = validate_result(
        cls,
        stages,
        web_resources=bad_resources,
        web_enrichment_enabled=False,
    )
    out_enabled = validate_result(
        cls,
        stages,
        web_resources=bad_resources,
        web_enrichment_enabled=True,
    )
    _check(
        "disabled: no web warning",
        not any(w.startswith("web_resources_missing_url") for w in out_disabled["warnings"]),
        str(out_disabled["warnings"]),
    )
    _check(
        "enabled: has web warning",
        any(w.startswith("web_resources_missing_url") for w in out_enabled["warnings"]),
        str(out_enabled["warnings"]),
    )


def test_semantic_conflict_detection():
    print("[test] semantic conflict detection")
    chunks = [
        {"chunk_id": "1", "source_name": "a", "chunk_text": "缓存策略必须启用"},
        {"chunk_id": "2", "source_name": "a", "chunk_text": "缓存策略不需要启用"},
    ]
    conflicts = detect_semantic_conflicts(chunks)
    _check("conflict detected", len(conflicts) >= 1, json.dumps(conflicts, ensure_ascii=False))


def test_topic_api_retries():
    print("[test] topic api retries")

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {"topic_label": "software_engineering", "confidence": 0.8, "reason": "ok"}
            ).encode("utf-8")

    calls = {"n": 0}

    def flaky_urlopen(req, timeout=0):
        calls["n"] += 1
        if calls["n"] == 1:
            raise tc.error.URLError("temporary")
        return FakeResp()

    old_urlopen = tc.request.urlopen
    old_url = os.environ.get("TOPIC_CLASSIFIER_API_URL")
    os.environ["TOPIC_CLASSIFIER_API_URL"] = "http://fake.local/topic"
    tc.request.urlopen = flaky_urlopen
    try:
        out = topic_coarse_classify(
            [
                {
                    "source_name": "x.md",
                    "source_path": "/tmp/x.md",
                    "source_type": "md",
                    "extracted_text": "软件工程",
                }
            ],
            mode="api",
            api_retries=1,
        )
    finally:
        tc.request.urlopen = old_urlopen
        if old_url is None:
            os.environ.pop("TOPIC_CLASSIFIER_API_URL", None)
        else:
            os.environ["TOPIC_CLASSIFIER_API_URL"] = old_url

    item = out["items"][0]
    _check("eventual api success", item["used_api"] is True, str(item))
    _check("retried twice", item["api_attempts"] == 2, str(item))


def test_api_assist_explicitly_enables_web_enrichment():
    print("[test] api assist explicitly enables web enrichment")
    tmp_dir = PROJECT_ROOT / "outputs" / "_tmp_test_api_assist"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_dir / "demo.md"
    src.write_text(
        "机器学习资料，补充链接：https://example.com/guide\n",
        encoding="utf-8",
    )

    old_url = os.environ.get("KNOWLEDGEHARNESS_API_URL")
    old_topic_urlopen = tc.request.urlopen
    old_web_urlopen = we.request.urlopen

    def fast_fail(req, timeout=0):
        raise tc.error.URLError("mock no network")

    os.environ["KNOWLEDGEHARNESS_API_URL"] = "http://fake.local/api"
    tc.request.urlopen = fast_fail
    we.request.urlopen = fast_fail
    try:
        out = run_pipeline(
            [str(src)],
            output_dir=str(tmp_dir),
            web_enrichment_enabled=False,
            web_enrichment_mode="auto",
            api_assist_enabled=True,
        )
    finally:
        tc.request.urlopen = old_topic_urlopen
        we.request.urlopen = old_web_urlopen
        if old_url is None:
            os.environ.pop("KNOWLEDGEHARNESS_API_URL", None)
        else:
            os.environ["KNOWLEDGEHARNESS_API_URL"] = old_url

    notes = out.get("pipeline_notes") or []
    resources = out.get("web_resources") or []
    _check(
        "auto-enable note present",
        any("api assist enabled: auto-enabled web enrichment" in n for n in notes),
        str(notes),
    )
    _check("fallback local resources available", len(resources) >= 1, str(resources))


def test_api_assist_disabled_keeps_local_mode():
    print("[test] api assist disabled keeps local mode")
    tmp_dir = PROJECT_ROOT / "outputs" / "_tmp_test_api_assist_off"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_dir / "demo.md"
    src.write_text(
        "机器学习资料，补充链接：https://example.com/guide\n",
        encoding="utf-8",
    )

    old_url = os.environ.get("KNOWLEDGEHARNESS_API_URL")
    old_topic_urlopen = tc.request.urlopen
    old_web_urlopen = we.request.urlopen

    def should_not_call(req, timeout=0):
        raise AssertionError("api should not be called when api assist is disabled")

    os.environ["KNOWLEDGEHARNESS_API_URL"] = "http://fake.local/api"
    tc.request.urlopen = should_not_call
    we.request.urlopen = should_not_call
    try:
        out = run_pipeline(
            [str(src)],
            output_dir=str(tmp_dir),
            web_enrichment_enabled=True,
            web_enrichment_mode="auto",
            api_assist_enabled=False,
        )
    finally:
        tc.request.urlopen = old_topic_urlopen
        we.request.urlopen = old_web_urlopen
        if old_url is None:
            os.environ.pop("KNOWLEDGEHARNESS_API_URL", None)
        else:
            os.environ["KNOWLEDGEHARNESS_API_URL"] = old_url

    notes = out.get("pipeline_notes") or []
    _check(
        "disabled note present",
        any("api assist disabled" in n for n in notes),
        str(notes),
    )


def test_content_classify_api_refines_unclassified():
    print("[test] content classify api refine")

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "category": "basic_concepts",
                    "confidence": 0.92,
                    "reason": "api refine",
                }
            ).encode("utf-8")

    old_urlopen = cn.request.urlopen
    old_url = os.environ.get("CONTENT_CLASSIFIER_API_URL")
    os.environ["CONTENT_CLASSIFIER_API_URL"] = "http://fake.local/classify"
    cn.request.urlopen = lambda req, timeout=0: FakeResp()
    try:
        out = classify_notes(
            [
                {
                    "chunk_id": "001",
                    "source_name": "x.md",
                    "source_type": "md",
                    "source_path": "/tmp/x.md",
                    "chunk_text": "%%#@ OCR 噪声片段",
                }
            ],
            api_assist_enabled=True,
        )
    finally:
        cn.request.urlopen = old_urlopen
        if old_url is None:
            os.environ.pop("CONTENT_CLASSIFIER_API_URL", None)
        else:
            os.environ["CONTENT_CLASSIFIER_API_URL"] = old_url

    item = out["chunks"][0]
    _check("api used", item.get("used_api") is True, str(item))
    _check("refined category", item.get("category") == "basic_concepts", str(item))


def test_stage_summarize_api_refines_stage3():
    print("[test] stage summarize api refine")

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "must_remember_concepts": ["监督学习是从标注数据学习映射。"],
                    "high_priority_points": ["先清洗，再划分训练/测试，再训练评估。"],
                    "easy_to_confuse_points": ["训练集泄漏会虚高指标。"],
                    "next_reading_directions": ["https://scikit-learn.org/stable/"],
                }
            ).encode("utf-8")

    old_urlopen = ss.request.urlopen
    old_url = os.environ.get("NOTES_ORGANIZER_API_URL")
    os.environ["NOTES_ORGANIZER_API_URL"] = "http://fake.local/organize"
    ss.request.urlopen = lambda req, timeout=0: FakeResp()
    try:
        out = stage_summarize(
            [{"source_name": "x.md"}],
            {
                "basic_concepts": [{"chunk_text": "概念：监督学习"}],
                "methods_and_processes": [{"chunk_text": "方法：先清洗再训练"}],
                "examples_and_applications": [],
                "difficult_or_error_prone_points": [{"chunk_text": "易错点：泄漏"}],
                "extended_reading": [{"chunk_text": "https://scikit-learn.org/stable/"}],
                "unclassified": [],
            },
            api_assist_enabled=True,
        )
    finally:
        ss.request.urlopen = old_urlopen
        if old_url is None:
            os.environ.pop("NOTES_ORGANIZER_API_URL", None)
        else:
            os.environ["NOTES_ORGANIZER_API_URL"] = old_url

    s3 = out.get("stage_3", {})
    _check("stage3 api used", s3.get("used_api") is True, str(s3))
    _check("stage3 concepts filled", len(s3.get("must_remember_concepts", [])) >= 1, str(s3))


def main():
    print("=" * 60)
    print("Phase-2 feature tests")
    print("=" * 60)
    test_web_enrichment_local_extracts_urls()
    test_validate_web_resource_link_check_only_when_enabled()
    test_semantic_conflict_detection()
    test_topic_api_retries()
    test_api_assist_explicitly_enables_web_enrichment()
    test_api_assist_disabled_keeps_local_mode()
    test_content_classify_api_refines_unclassified()
    test_stage_summarize_api_refines_stage3()
    print("-" * 60)
    print(f"Result: {_passed} passed, {_failed} failed")
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
