"""Minimal CLI app to run KnowledgeHarness MVP pipeline."""

from __future__ import annotations

import argparse
import glob
import os
from pathlib import Path
from typing import Any, Dict, List

from tools.chunk_notes import chunk_notes
from tools.classify_notes import classify_notes
from tools.export_notes import export_notes
from tools.export_word import export_word_from_markdown
from tools.extract_keypoints import extract_keypoints
from tools.parse_inputs import SUPPORTED_EXTENSIONS, parse_inputs
from tools.detect_semantic_conflicts import detect_semantic_conflicts
from tools.runtime_config import load_runtime_config
from tools.stage_summarize import stage_summarize
from tools.topic_coarse_classify import topic_coarse_classify
from tools.validate_result import validate_result
from tools.web_enrichment import web_enrich

# Directories that are part of the project itself; when the user points
# app.py at a parent directory we skip these to avoid treating project
# documentation as user study material. `uploads/` is where the optional
# Web UI stores freshly-uploaded files — we skip it so a later `python3
# app.py .` run does not re-ingest previously-uploaded material.
EXCLUDED_DIR_NAMES = {
    "outputs",
    "docs",
    "project_memory",
    ".codex",
    ".git",
    "__pycache__",
    ".venv",
    "uploads",
}


def _is_under_excluded_dir(path: Path) -> bool:
    return any(part in EXCLUDED_DIR_NAMES for part in path.parts)


def collect_input_files(inputs: List[str]) -> List[str]:
    """Collect file paths from explicit files, directories, and glob patterns.

    Project-meta directories (docs/, outputs/, project_memory/, .codex/, .git/)
    are filtered out automatically so running the pipeline on the project
    root never pulls in our own documentation as "user material".
    Explicit single-file arguments are always honored.

    Directory-mode globs cover the full declared support surface:
    ``tools.parse_inputs.SUPPORTED_EXTENSIONS``.
    """
    # Drive glob from the single source of truth so new extensions added in
    # parse_inputs automatically become pickable in dir mode.
    dir_glob_patterns = [f"*{ext}" for ext in sorted(SUPPORTED_EXTENSIONS)]

    files: List[str] = []
    for item in inputs:
        p = Path(item)
        if p.is_dir():
            if p.name in EXCLUDED_DIR_NAMES:
                continue
            for pattern in dir_glob_patterns:
                for f in p.glob(pattern):
                    if _is_under_excluded_dir(f):
                        continue
                    files.append(str(f))
        elif p.is_file():
            # Explicit file arguments are accepted unconditionally, even
            # when the file happens to live inside an excluded directory
            # (e.g. the Web UI's `uploads/ui_uploads/` staging area).
            files.append(str(p))
        else:
            matches = glob.glob(item)
            if matches:
                for m in matches:
                    mp = Path(m)
                    if _is_under_excluded_dir(mp):
                        continue
                    files.append(m)

    # Stable unique order.
    deduped: List[str] = []
    seen = set()
    for f in files:
        key = str(Path(f).resolve())
        if key not in seen:
            seen.add(key)
            deduped.append(f)
    return deduped


def _cli_ingest_notifier(event: str, payload: Dict[str, Any]) -> None:
    """Print human-readable ingestion progress to stdout."""
    if event == "detected":
        eff = payload.get("supported_extensions_effective") or []
        backend = payload.get("ocr_backend", "unavailable")
        print(f"[ingest] detected {payload.get('count', 0)} file(s)")
        print(f"[ingest] effective supported extensions: {', '.join(eff) or '(none)'}")
        print(f"[ingest] ocr backend: {backend}")
    elif event == "start":
        tag = "supported" if payload.get("supported") else "UNSUPPORTED"
        src_type = payload.get("source_type") or "?"
        print(
            f"[ingest] {payload.get('source_name')} ({src_type}) {tag}, parsing..."
        )
    elif event == "success":
        flag = "EMPTY" if payload.get("empty") else "OK"
        print(
            f"[ingest] {payload.get('source_name')} {flag}, "
            f"{payload.get('chars', 0)} chars"
        )
    elif event == "failed":
        print(
            f"[ingest] {payload.get('source_name')} FAILED "
            f"reason={payload.get('reason')} | {payload.get('error', '')}"
        )
    elif event == "summary":
        print(
            "[ingest] summary: "
            f"detected={payload.get('detected', 0)}, "
            f"ok={payload.get('succeeded', 0)}, "
            f"empty={payload.get('empty_extracted', 0)}, "
            f"failed={payload.get('failed', 0)}"
        )


def _load_local_env(path: str = ".env") -> None:
    """Load KEY=VALUE pairs from local .env (without overriding existing env)."""
    env_file = Path(path)
    if not env_file.exists() or not env_file.is_file():
        return

    for line in env_file.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, val = s.split("=", 1)
        key = key.strip()
        val = val.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = val


def run_pipeline(
    input_files: List[str],
    output_dir: str = "outputs",
    topic_taxonomy_path: str | None = None,
    topic_mode: str = "auto",
    topic_api_timeout: float = 6.0,
    topic_api_retries: int = 1,
    web_enrichment_enabled: bool = False,
    web_enrichment_mode: str = "auto",
    web_enrichment_timeout: float = 6.0,
    web_enrichment_max_items: int = 8,
    keypoint_min_confidence: float = 0.0,
    keypoint_max_points: int = 12,
    chunk_max_chars: int = 500,
    classification_keywords: dict | None = None,
    classification_label_hints: dict | None = None,
    classification_category_priority: list | None = None,
    ocr_languages: str = "chi_sim+eng",
    ocr_fallback_language: str = "eng",
    markdown_use_details: bool = False,
    final_notes_only: bool = True,
    export_docx: bool = False,
    pre_pipeline_notes: list | None = None,
    notifier=None,
) -> dict:
    parsed = parse_inputs(
        input_files,
        notifier=notifier,
        ocr_languages=ocr_languages,
        ocr_fallback_language=ocr_fallback_language,
    )
    documents = parsed["documents"]
    logs = parsed.get("logs", {}) or {}
    failed_sources = logs.get("failed_sources", []) or []
    empty_sources = logs.get("empty_extracted_sources", []) or []
    ingestion_summary = parsed.get("ingestion_summary", {}) or {}

    chunks = chunk_notes(documents, max_chars=chunk_max_chars)
    topic_output = topic_coarse_classify(
        documents,
        taxonomy_path=topic_taxonomy_path,
        mode=topic_mode,
        api_timeout_sec=topic_api_timeout,
        api_retries=topic_api_retries,
    )
    classified_output = classify_notes(
        chunks,
        keywords=classification_keywords,
        label_hints=classification_label_hints,
        category_priority=classification_category_priority,
    )

    # Must classify before summarize.
    summaries = stage_summarize(documents, classified_output["categorized"])
    keypoints = extract_keypoints(
        classified_output["categorized"],
        max_points=keypoint_max_points,
        min_confidence=keypoint_min_confidence,
    )

    enrichment_output = web_enrich(
        documents,
        enabled=web_enrichment_enabled,
        mode=web_enrichment_mode,
        timeout_sec=web_enrichment_timeout,
        max_items=web_enrichment_max_items,
    )
    web_resources: List[dict] = enrichment_output.get("resources", []) or []
    semantic_conflicts = detect_semantic_conflicts(
        classified_output.get("chunks", []) or []
    )

    validation = validate_result(
        classified_output,
        summaries,
        failed_sources=failed_sources,
        empty_sources=empty_sources,
        web_resources=web_resources,
        web_enrichment_enabled=web_enrichment_enabled,
        semantic_conflicts=semantic_conflicts,
    )

    # review_needed stays chunk-level only; system-level signals go to
    # pipeline_notes so the two concerns do not cross-contaminate.
    review_needed = list(classified_output.get("review_needed", []))
    pipeline_notes: List[str] = list(pre_pipeline_notes or [])

    # Surface "no usable input text" so downstream readers understand why
    # categorized_notes / key_points may be empty.
    if input_files and not documents:
        pipeline_notes.append(
            "no usable input text: every detected file failed or was empty"
        )

    if topic_output.get("warnings"):
        pipeline_notes.append(
            "topic coarse classification warnings: "
            + " | ".join(topic_output["warnings"])
        )

    if enrichment_output.get("warnings"):
        pipeline_notes.append(
            "web enrichment warnings: " + " | ".join(enrichment_output["warnings"])
        )

    if semantic_conflicts:
        pipeline_notes.append(
            f"semantic conflicts detected: {len(semantic_conflicts)} pair(s)"
        )

    if validation.get("warnings"):
        pipeline_notes.append(
            "validation warnings: " + ",".join(validation["warnings"])
        )

    result = {
        "overview": {
            "source_count": len(documents),
            "chunk_count": len(chunks),
            "failed_sources": failed_sources,
            "empty_extracted_sources": empty_sources,
            "ingestion_summary": ingestion_summary,
        },
        "source_documents": documents,
        "topic_classification": topic_output,
        "categorized_notes": classified_output["categorized"],
        "stage_summaries": summaries,
        "key_points": keypoints,
        "web_resources": web_resources,
        "semantic_conflicts": semantic_conflicts,
        "review_needed": review_needed,
        "pipeline_notes": pipeline_notes,
        "validation": validation,
    }

    export_paths = export_notes(
        result,
        out_dir=output_dir,
        markdown_use_details=markdown_use_details,
        final_notes_only=final_notes_only,
    )
    if export_docx:
        try:
            export_paths["docx_path"] = export_word_from_markdown(
                export_paths["md_path"],
                out_dir=output_dir,
                filename="result.docx",
            )
        except Exception as exc:
            result["pipeline_notes"].append(f"word export failed: {exc}")
    result["export_paths"] = export_paths
    return result


def main() -> None:
    _load_local_env(".env")
    parser = argparse.ArgumentParser(description="KnowledgeHarness MVP")
    parser.add_argument("inputs", nargs="+", help="Input files / dirs / globs")
    parser.add_argument("--output-dir", default="outputs", help="Output directory")
    parser.add_argument(
        "--config",
        default="config/pipeline_config.json",
        help="Runtime config JSON path",
    )
    parser.add_argument(
        "--topic-taxonomy",
        default="config/topic_taxonomy.json",
        help="Path to constrained topic label taxonomy JSON",
    )
    parser.add_argument(
        "--topic-mode",
        default=None,
        choices=["auto", "local", "api"],
        help="Topic coarse classifier mode: auto/local/api",
    )
    parser.add_argument(
        "--topic-api-timeout",
        default=None,
        type=float,
        help="Timeout seconds for optional topic API calls",
    )
    parser.add_argument(
        "--topic-api-retries",
        default=None,
        type=int,
        help="Retry count for topic API on recoverable failures",
    )
    parser.add_argument(
        "--enable-web-enrichment",
        action="store_true",
        help="Enable supplementary web enrichment",
    )
    parser.add_argument(
        "--web-enrichment-mode",
        default=None,
        choices=["off", "local", "api", "auto"],
        help="Web enrichment mode",
    )
    parser.add_argument(
        "--web-enrichment-timeout",
        default=None,
        type=float,
        help="Timeout seconds for web enrichment API calls",
    )
    parser.add_argument(
        "--web-enrichment-max-items",
        default=None,
        type=int,
        help="Maximum web resources to keep",
    )
    parser.add_argument(
        "--keypoint-max-points",
        default=None,
        type=int,
        help="Maximum number of key points",
    )
    parser.add_argument(
        "--keypoint-min-confidence",
        default=None,
        type=float,
        help="Optional confidence threshold for key point extraction",
    )
    parser.add_argument(
        "--export-docx",
        action="store_true",
        help="Also export final result as Word (.docx)",
    )
    parser.add_argument(
        "--full-report",
        action="store_true",
        help="Export full markdown report instead of final-notes-only markdown",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-file ingestion progress output",
    )
    args = parser.parse_args()
    runtime_conf, conf_warnings = load_runtime_config(args.config)

    files = collect_input_files(args.inputs)
    if not files:
        raise SystemExit("No valid input files found.")

    notifier = None if args.quiet else _cli_ingest_notifier
    topic_conf = runtime_conf.get("topic", {}) or {}
    web_conf = runtime_conf.get("web_enrichment", {}) or {}
    key_conf = runtime_conf.get("key_points", {}) or {}
    chunk_conf = runtime_conf.get("chunking", {}) or {}
    cls_conf = runtime_conf.get("classification", {}) or {}
    ocr_conf = runtime_conf.get("ocr", {}) or {}
    export_conf = runtime_conf.get("export", {}) or {}
    final_notes_default = bool(export_conf.get("final_notes_only", True))
    topic_mode_effective = args.topic_mode or topic_conf.get("mode", "auto")
    web_mode_effective = args.web_enrichment_mode or web_conf.get("mode", "auto")

    has_topic_api = bool(
        os.getenv("TOPIC_CLASSIFIER_API_URL", "").strip()
        or os.getenv("KNOWLEDGEHARNESS_API_URL", "").strip()
    )
    has_web_api = bool(
        os.getenv("WEB_ENRICHMENT_API_URL", "").strip()
        or os.getenv("KNOWLEDGEHARNESS_API_URL", "").strip()
    )

    if topic_mode_effective == "api" and not has_topic_api:
        print("[api] topic classifier: 请接入API后使用")
    if (
        bool(args.enable_web_enrichment) or bool(web_conf.get("enabled", False))
    ) and web_mode_effective == "api" and not has_web_api:
        print("[api] web enrichment: 请接入API后使用")

    result = run_pipeline(
        files,
        output_dir=args.output_dir,
        topic_taxonomy_path=args.topic_taxonomy,
        topic_mode=topic_mode_effective,
        topic_api_timeout=float(
            args.topic_api_timeout
            if args.topic_api_timeout is not None
            else topic_conf.get("api_timeout_sec", 6.0)
        ),
        topic_api_retries=int(
            args.topic_api_retries
            if args.topic_api_retries is not None
            else topic_conf.get("api_retries", 1)
        ),
        web_enrichment_enabled=(
            bool(args.enable_web_enrichment) or bool(web_conf.get("enabled", False))
        ),
        web_enrichment_mode=web_mode_effective,
        web_enrichment_timeout=float(
            args.web_enrichment_timeout
            if args.web_enrichment_timeout is not None
            else web_conf.get("timeout_sec", 6.0)
        ),
        web_enrichment_max_items=int(
            args.web_enrichment_max_items
            if args.web_enrichment_max_items is not None
            else web_conf.get("max_items", 8)
        ),
        keypoint_min_confidence=float(
            args.keypoint_min_confidence
            if args.keypoint_min_confidence is not None
            else key_conf.get("min_confidence", 0.0)
        ),
        keypoint_max_points=int(
            args.keypoint_max_points
            if args.keypoint_max_points is not None
            else key_conf.get("max_points", 12)
        ),
        chunk_max_chars=int(chunk_conf.get("max_chars", 500)),
        classification_keywords=cls_conf.get("keywords"),
        classification_label_hints=cls_conf.get("label_hints"),
        classification_category_priority=cls_conf.get("category_priority"),
        ocr_languages=str(ocr_conf.get("languages", "chi_sim+eng")),
        ocr_fallback_language=str(ocr_conf.get("fallback_language", "eng")),
        markdown_use_details=bool(export_conf.get("markdown_use_details", False)),
        final_notes_only=(not bool(args.full_report)) and final_notes_default,
        export_docx=bool(args.export_docx or export_conf.get("export_docx", False)),
        pre_pipeline_notes=[f"runtime config warning: {w}" for w in conf_warnings],
        notifier=notifier,
    )
    validation = result.get("validation", {}) or {}
    print("Pipeline completed.")
    print(f"JSON: {result['export_paths']['json_path']}")
    print(f"MD:   {result['export_paths']['md_path']}")
    if result["export_paths"].get("docx_path"):
        print(f"DOCX: {result['export_paths']['docx_path']}")
    print(f"is_valid: {validation.get('is_valid')}")
    warnings = validation.get("warnings") or []
    print(f"warnings: {warnings if warnings else '(none)'}")


if __name__ == "__main__":
    main()
