"""Minimal stdlib-only tests for the Input Expansion module.

Run directly:

    python3 tests/test_parse_inputs.py

Covered:
- unsupported file type -> failed_sources with reason=unsupported_file_type
- empty text file        -> empty_extracted_sources
- txt / md               -> documents
- docx                   -> documents (requires python-docx)
- image w/o OCR backend  -> failed_sources with reason=ocr_backend_unavailable
- notifier event stream  -> detected / start / success|failed / summary

NOTE: This script is self-contained and does NOT require pytest.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Make the project importable when running `python3 tests/test_parse_inputs.py`.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.parse_inputs import (  # noqa: E402
    FILE_NOT_FOUND,
    IMAGE_EXTENSIONS,
    OCR_BACKEND_UNAVAILABLE,
    PARSE_ERROR,
    SUPPORTED_EXTENSIONS,
    UNSUPPORTED_FILE_TYPE,
    parse_inputs,
)


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


def test_supported_extensions_declared():
    print("[test] supported extension surface")
    for ext in (".txt", ".md", ".pdf", ".docx", ".png", ".jpg", ".jpeg"):
        _check(f"{ext} declared", ext in SUPPORTED_EXTENSIONS)


def test_unsupported_file_type():
    print("[test] unsupported file type")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "foo.log"
        p.write_text("noop", encoding="utf-8")
        result = parse_inputs([str(p)])
        failed = result["logs"]["failed_sources"]
        _check("one failed entry", len(failed) == 1, str(failed))
        _check(
            "reason tag",
            failed and failed[0]["reason"] == UNSUPPORTED_FILE_TYPE,
            str(failed),
        )
        _check(
            "source_type carried",
            failed and failed[0]["source_type"] == "log",
            str(failed),
        )


def test_txt_and_empty():
    print("[test] txt ok + empty txt")
    with tempfile.TemporaryDirectory() as d:
        good = Path(d) / "good.txt"
        good.write_text("hello world", encoding="utf-8")
        empty = Path(d) / "empty.txt"
        empty.write_text("   \n\n  ", encoding="utf-8")
        result = parse_inputs([str(good), str(empty)])
        _check("two documents", len(result["documents"]) == 2)
        empties = result["logs"]["empty_extracted_sources"]
        _check("empty recorded", "empty.txt" in empties, str(empties))
        summary = result["ingestion_summary"]
        _check("summary detected", summary["detected"] == 2)
        _check("summary succeeded=1", summary["succeeded"] == 1, str(summary))
        _check("summary empty=1", summary["empty_extracted"] == 1, str(summary))


def test_missing_file():
    print("[test] file not found")
    result = parse_inputs(["/no/such/file.md"])
    failed = result["logs"]["failed_sources"]
    _check("one failed", len(failed) == 1)
    _check(
        "reason=file_not_found",
        failed and failed[0]["reason"] == FILE_NOT_FOUND,
        str(failed),
    )


def test_docx_roundtrip():
    print("[test] docx happy path")
    try:
        from docx import Document
    except Exception as exc:
        _check("python-docx available", False, f"import failed: {exc}")
        return
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "note.docx"
        doc = Document()
        doc.add_paragraph("基础概念：监督学习是从标注数据学习映射。")
        doc.add_paragraph("方法步骤：清洗、切分、训练。")
        doc.save(str(p))
        result = parse_inputs([str(p)])
        docs = result["documents"]
        _check("docx parsed", len(docs) == 1, str(result))
        if docs:
            _check(
                "source_type=docx",
                docs[0]["source_type"] == "docx",
                str(docs[0]),
            )
            _check(
                "text extracted",
                "监督学习" in docs[0]["extracted_text"],
                docs[0]["extracted_text"][:80],
            )


def test_image_degrades_without_backend():
    print("[test] image without OCR backend degrades gracefully")
    # Create a tiny 1x1 file. We don't need a real image because probe fails
    # before the reader actually opens the file -- in this sandbox the
    # tesseract binary is missing, so the OCR probe must short-circuit.
    import shutil

    if shutil.which("tesseract"):
        print("  SKIP: tesseract binary is present; degrade path not applicable")
        return

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "fake.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\n")  # just the PNG signature
        result = parse_inputs([str(p)])
        failed = result["logs"]["failed_sources"]
        _check("one failed", len(failed) == 1, str(failed))
        if failed:
            _check(
                "reason=ocr_backend_unavailable",
                failed[0]["reason"] == OCR_BACKEND_UNAVAILABLE,
                str(failed[0]),
            )


def test_notifier_event_stream():
    print("[test] notifier fires expected events")
    events = []

    def recorder(event, payload):
        events.append((event, payload))

    with tempfile.TemporaryDirectory() as d:
        good = Path(d) / "good.txt"
        good.write_text("hi", encoding="utf-8")
        bad = Path(d) / "weird.log"
        bad.write_text("x", encoding="utf-8")
        parse_inputs([str(good), str(bad)], notifier=recorder)

    names = [e[0] for e in events]
    _check("detected first", names[0] == "detected", str(names))
    _check("summary last", names[-1] == "summary", str(names))
    _check("has start events", names.count("start") == 2, str(names))
    _check("has one success", names.count("success") == 1, str(names))
    _check("has one failed", names.count("failed") == 1, str(names))


def main():
    print("=" * 60)
    print("Input Expansion + Ingestion Notice: minimal tests")
    print("=" * 60)
    test_supported_extensions_declared()
    test_unsupported_file_type()
    test_txt_and_empty()
    test_missing_file()
    test_docx_roundtrip()
    test_image_degrades_without_backend()
    test_notifier_event_stream()
    print("-" * 60)
    print(f"Result: {_passed} passed, {_failed} failed")
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
