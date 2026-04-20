"""Stage-1 core regression tests (stdlib-only).

Run directly:

    python3 tests/test_stage1_core.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app import run_pipeline  # noqa: E402
from tools.chunk_notes import chunk_notes  # noqa: E402
from tools.classify_notes import classify_notes  # noqa: E402
from tools.export_notes import export_notes  # noqa: E402
from tools.validate_result import validate_result  # noqa: E402

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


def test_chunk_hard_split():
    print("[test] chunk hard split")
    docs = [
        {
            "source_name": "a.md",
            "source_type": "md",
            "source_path": "/tmp/a.md",
            "raw_text": "",
            "extracted_text": "a" * 25,
        }
    ]
    chunks = chunk_notes(docs, max_chars=10)
    lens = [len(c["chunk_text"]) for c in chunks]
    _check("has multiple chunks", len(chunks) >= 3, str(lens))
    _check("all <= max_chars", all(x <= 10 for x in lens), str(lens))


def test_classify_tie_and_review_needed():
    print("[test] classify tie -> review_needed")
    chunks = [
        {
            "chunk_id": "000-0000",
            "source_name": "a.md",
            "source_type": "md",
            "source_path": "/tmp/a.md",
            "raw_text": "",
            "extracted_text": "",
            "chunk_text": "方法 案例",
        }
    ]
    out = classify_notes(chunks)
    item = out["chunks"][0]
    _check("tie reason", "tie resolved by category priority" in item["classification_reason"], str(item))
    _check("review needed appended", len(out["review_needed"]) == 1, str(out["review_needed"]))


def test_validate_warnings():
    print("[test] validate warnings")
    classification_output = {
        "chunks": [{"chunk_id": "1", "chunk_text": "重复文本"}, {"chunk_id": "2", "chunk_text": "重复文本"}],
        "categorized": {
            "basic_concepts": [],
            "methods_and_processes": [],
            "examples_and_applications": [],
            "difficult_or_error_prone_points": [],
            "extended_reading": [],
            "unclassified": [{"chunk_id": "1"}, {"chunk_id": "2"}],
        },
    }
    out = validate_result(
        classification_output,
        stage_summaries={"stage_1": {}, "stage_2": {}},
        failed_sources=[{"source": "a"}],
        empty_sources=["b"],
    )
    warnings = out["warnings"]
    _check("too_many_unclassified", "too_many_unclassified_chunks" in warnings, str(warnings))
    _check("duplicated", "duplicated_chunks_detected" in warnings, str(warnings))
    _check("missing_stage_3", any(w.startswith("missing_stage_summaries:") for w in warnings), str(warnings))
    _check("failed_sources warning", "failed_sources_present:1" in warnings, str(warnings))


def test_export_contains_topic_section():
    print("[test] export includes topic section")
    result = {
        "overview": {"source_count": 1, "chunk_count": 0},
        "source_documents": [],
        "topic_classification": {
            "mode_requested": "local",
            "stats": {"document_count": 1, "used_api_count": 0, "degraded_count": 0, "counts_by_label": {"unknown_topic": 1}},
            "items": [{"source_name": "x.md", "topic_label": "unknown_topic", "confidence": 0.0, "used_api": False}],
        },
        "categorized_notes": {},
        "stage_summaries": {"stage_1": {}, "stage_2": {}, "stage_3": {}},
        "key_points": {"key_points": []},
        "web_resources": [],
        "review_needed": [],
        "pipeline_notes": [],
        "validation": {"is_valid": True, "warnings": []},
    }
    with tempfile.TemporaryDirectory() as d:
        paths = export_notes(result, out_dir=d)
        md_text = Path(paths["md_path"]).read_text(encoding="utf-8")
        json_obj = json.loads(Path(paths["json_path"]).read_text(encoding="utf-8"))
    _check("md has topic overview", "## Topic Overview" in md_text)
    _check("json has topic key", "topic_classification" in json_obj)


def test_run_pipeline_regressions():
    print("[test] app.run_pipeline regressions")
    with tempfile.TemporaryDirectory() as d:
        good = Path(d) / "good.md"
        good.write_text("概念：监督学习", encoding="utf-8")

        bad = Path(d) / "bad.log"
        bad.write_text("x", encoding="utf-8")

        out_ok = run_pipeline([str(good)], output_dir=d, topic_mode="local")
        _check("run ok has topic", "topic_classification" in out_ok, str(out_ok.keys()))
        _check("run ok has validation", "validation" in out_ok, str(out_ok.keys()))

        out_bad = run_pipeline([str(bad)], output_dir=d, topic_mode="local")
        notes = out_bad.get("pipeline_notes", [])
        _check("failed-only no usable note", any("no usable input text" in n for n in notes), str(notes))
        _check("review_needed chunk-only", out_bad.get("review_needed", []) == [], str(out_bad.get("review_needed")))


def test_keypoint_min_confidence_filter():
    print("[test] keypoint confidence threshold")
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "mix.md"
        f.write_text(
            "方法：先清洗数据。\\n\\n方法 示例\\n\\n例如：一个案例。\\n\\n易错点：注意泄漏。",
            encoding="utf-8",
        )
        out = run_pipeline(
            [str(f)],
            output_dir=d,
            topic_mode="local",
            keypoint_min_confidence=0.6,
        )
        points = out.get("key_points", {}).get("key_points", [])
        stats = out.get("key_points", {}).get("stats", {})
        _check("threshold recorded", float(stats.get("min_confidence", -1)) == 0.6, str(stats))
        _check("has key points", len(points) >= 1, str(points))


def main():
    print("=" * 60)
    print("Stage-1 core regression tests")
    print("=" * 60)
    test_chunk_hard_split()
    test_classify_tie_and_review_needed()
    test_validate_warnings()
    test_export_contains_topic_section()
    test_run_pipeline_regressions()
    test_keypoint_min_confidence_filter()
    print("-" * 60)
    print(f"Result: {_passed} passed, {_failed} failed")
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
