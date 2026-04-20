"""Phase-3 (non-API) tests: config/runtime/export enhancements.

Run directly:

    python3 tests/test_phase3_non_api.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app import run_pipeline  # noqa: E402
from tools.runtime_config import load_runtime_config  # noqa: E402
from tools.export_notes import export_notes  # noqa: E402

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


def test_runtime_config_merge():
    print("[test] runtime config merge")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "cfg.json"
        p.write_text(
            json.dumps(
                {
                    "chunking": {"max_chars": 120},
                    "key_points": {"min_confidence": 0.8},
                }
            ),
            encoding="utf-8",
        )
        conf, warns = load_runtime_config(str(p))
    _check("no warnings", warns == [], str(warns))
    _check("chunk max overridden", conf["chunking"]["max_chars"] == 120, str(conf))
    _check("other defaults preserved", conf["topic"]["api_retries"] == 1, str(conf))


def test_markdown_details_export():
    print("[test] markdown details export")
    result = {
        "overview": {"source_count": 1, "chunk_count": 1},
        "source_documents": [],
        "topic_classification": {"mode_requested": "local", "stats": {}, "items": []},
        "categorized_notes": {"basic_concepts": [{"chunk_id": "1", "source_name": "a", "chunk_text": "概念", "confidence": 0.8}]},
        "stage_summaries": {"stage_1": {}, "stage_2": {}, "stage_3": {}},
        "key_points": {"key_points": []},
        "web_resources": [],
        "semantic_conflicts": [],
        "review_needed": [],
        "pipeline_notes": [],
        "validation": {"is_valid": True, "warnings": []},
    }
    with tempfile.TemporaryDirectory() as d:
        paths = export_notes(result, out_dir=d, markdown_use_details=True)
        md = Path(paths["md_path"]).read_text(encoding="utf-8")
    _check("details tag present", "<details><summary>basic_concepts" in md, md[:200])


def test_run_pipeline_keypoint_max_points():
    print("[test] keypoint max_points")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "a.md"
        p.write_text(
            "易错点：A\n\n易错点：B\n\n易错点：C\n\n易错点：D",
            encoding="utf-8",
        )
        out = run_pipeline([str(p)], output_dir=d, keypoint_max_points=2, topic_mode="local")
    points = out.get("key_points", {}).get("key_points", [])
    _check("points capped", len(points) <= 2, str(points))


def main():
    print("=" * 60)
    print("Phase-3 non-API tests")
    print("=" * 60)
    test_runtime_config_merge()
    test_markdown_details_export()
    test_run_pipeline_keypoint_max_points()
    print("-" * 60)
    print(f"Result: {_passed} passed, {_failed} failed")
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
