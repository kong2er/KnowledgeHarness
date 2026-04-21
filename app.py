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
from tools.pipeline_runtime import (
    build_pipeline_run_kwargs,
    load_local_env,
)
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
    web_enrichment_api_retries: int = 1,
    api_assist_enabled: bool = False,
    keypoint_min_confidence: float = 0.0,
    keypoint_max_points: int = 12,
    chunk_max_chars: int = 500,
    classification_keywords: dict | None = None,
    classification_label_hints: dict | None = None,
    classification_category_priority: list | None = None,
    ocr_languages: str = "chi_sim+eng",
    ocr_fallback_language: str = "eng",
    image_api_timeout_sec: float = 8.0,
    image_api_retries: int = 1,
    image_api_enhance_mode: str = "auto",
    image_api_enhance_min_score: int = 40,
    image_api_enhance_ratio: float = 1.1,
    image_api_enhance_min_delta: int = 6,
    validation_profile: str = "strict",
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
        api_assist_enabled=api_assist_enabled,
        image_api_timeout_sec=image_api_timeout_sec,
        image_api_retries=image_api_retries,
        image_api_enhance_mode=image_api_enhance_mode,
        image_api_enhance_min_score=image_api_enhance_min_score,
        image_api_enhance_ratio=image_api_enhance_ratio,
        image_api_enhance_min_delta=image_api_enhance_min_delta,
    )
    documents = parsed["documents"]
    logs = parsed.get("logs", {}) or {}
    failed_sources = logs.get("failed_sources", []) or []
    empty_sources = logs.get("empty_extracted_sources", []) or []
    ingestion_summary = parsed.get("ingestion_summary", {}) or {}

    chunks = chunk_notes(documents, max_chars=chunk_max_chars)
    topic_mode_norm = (topic_mode or "auto").strip().lower()
    topic_mode_effective = topic_mode_norm
    if topic_mode_norm == "auto" and not api_assist_enabled:
        topic_mode_effective = "local"

    topic_output = topic_coarse_classify(
        documents,
        taxonomy_path=topic_taxonomy_path,
        mode=topic_mode_effective,
        api_timeout_sec=topic_api_timeout,
        api_retries=topic_api_retries,
    )
    classified_output = classify_notes(
        chunks,
        keywords=classification_keywords,
        label_hints=classification_label_hints,
        category_priority=classification_category_priority,
        api_assist_enabled=api_assist_enabled,
        api_timeout_sec=topic_api_timeout,
        api_retries=topic_api_retries,
    )

    # Must classify before summarize.
    summaries = stage_summarize(
        documents,
        classified_output["categorized"],
        api_assist_enabled=api_assist_enabled,
        api_timeout_sec=topic_api_timeout,
        api_retries=topic_api_retries,
    )
    keypoints = extract_keypoints(
        classified_output["categorized"],
        max_points=keypoint_max_points,
        min_confidence=keypoint_min_confidence,
    )

    has_any_api = bool(
        os.getenv("WEB_ENRICHMENT_API_URL", "").strip()
        or os.getenv("KNOWLEDGEHARNESS_API_URL", "").strip()
    )
    web_mode_norm = (web_enrichment_mode or "auto").strip().lower()
    web_mode_effective = web_mode_norm
    if web_mode_norm == "auto" and not api_assist_enabled:
        web_mode_effective = "local"
    web_enabled_effective = bool(web_enrichment_enabled)
    auto_enabled_web = False
    if (
        not web_enabled_effective
        and api_assist_enabled
        and has_any_api
        and web_mode_norm in {"auto", "api"}
    ):
        # User explicitly enabled API assist; auto-lift enrichment for tangible gain.
        web_enabled_effective = True
        auto_enabled_web = True

    enrichment_output = web_enrich(
        documents,
        enabled=web_enabled_effective,
        mode=web_mode_effective,
        timeout_sec=web_enrichment_timeout,
        max_items=web_enrichment_max_items,
        api_retries=web_enrichment_api_retries,
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
        web_enrichment_enabled=web_enabled_effective,
        semantic_conflicts=semantic_conflicts,
        validation_profile=validation_profile,
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
    image_api_succeeded = int(ingestion_summary.get("image_api_succeeded", 0) or 0)
    image_api_attempted = int(ingestion_summary.get("image_api_attempted", 0) or 0)
    image_api_enhanced = int(ingestion_summary.get("image_api_enhanced", 0) or 0)
    if image_api_attempted > 0 and image_api_succeeded == 0:
        pipeline_notes.append(
            f"image api ocr attempted but not used: {image_api_attempted} attempt(s)"
        )
    if image_api_succeeded > 0:
        if image_api_enhanced > 0:
            pipeline_notes.append(
                f"image api ocr enhanced local result: {image_api_enhanced} file(s)"
            )
        else:
            pipeline_notes.append(
                f"image api ocr assisted: {image_api_succeeded} file(s)"
            )
    if has_any_api and not api_assist_enabled:
        pipeline_notes.append(
            "api assist disabled: using local-only strategy unless explicitly set to api mode"
        )
    if auto_enabled_web:
        pipeline_notes.append(
            "api assist enabled: auto-enabled web enrichment for this run"
        )

    if topic_output.get("warnings"):
        pipeline_notes.append(
            "topic coarse classification warnings: "
            + " | ".join(topic_output["warnings"])
        )

    if classified_output.get("warnings"):
        pipeline_notes.append(
            "content classification warnings: "
            + " | ".join(classified_output["warnings"])
        )

    if summaries.get("warnings"):
        pipeline_notes.append(
            "stage summarize warnings: "
            + " | ".join(summaries["warnings"])
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
    load_local_env(".env")
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
        "--web-enrichment-api-retries",
        default=None,
        type=int,
        help="Retry count for web enrichment API on recoverable failures",
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
        "--validation-profile",
        default=None,
        choices=["strict", "lenient"],
        help="Validation strictness profile: strict/lenient",
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
    parser.add_argument(
        "--enable-api-assist",
        action="store_true",
        help="Explicitly enable optional API-assisted stages (default: off/local-first)",
    )
    args = parser.parse_args()
    files = collect_input_files(args.inputs)
    if not files:
        raise SystemExit("No valid input files found.")

    notifier = None if args.quiet else _cli_ingest_notifier
    run_kwargs, runtime_meta = build_pipeline_run_kwargs(
        config_path=args.config,
        topic_mode=args.topic_mode,
        topic_api_timeout=args.topic_api_timeout,
        topic_api_retries=args.topic_api_retries,
        web_enrichment_enabled=(True if args.enable_web_enrichment else None),
        web_enrichment_mode=args.web_enrichment_mode,
        web_enrichment_timeout=args.web_enrichment_timeout,
        web_enrichment_max_items=args.web_enrichment_max_items,
        web_enrichment_api_retries=args.web_enrichment_api_retries,
        api_assist_enabled=(True if args.enable_api_assist else None),
        keypoint_min_confidence=args.keypoint_min_confidence,
        keypoint_max_points=args.keypoint_max_points,
        validation_profile=args.validation_profile,
        export_docx=(True if args.export_docx else None),
        full_report=bool(args.full_report),
    )

    topic_mode_effective = str(runtime_meta.get("topic_mode", "auto"))
    web_mode_effective = str(runtime_meta.get("web_enrichment_mode", "auto"))
    web_enabled_effective = bool(runtime_meta.get("web_enrichment_enabled", False))
    has_topic_api = bool(runtime_meta.get("has_topic_api", False))
    has_web_api = bool(runtime_meta.get("has_web_api", False))

    if topic_mode_effective.lower() == "api" and not has_topic_api:
        print("[api] topic classifier: 请接入API后使用")
    if (
        web_enabled_effective
        and web_mode_effective.lower() == "api"
        and not has_web_api
    ):
        print("[api] web enrichment: 请接入API后使用")

    result = run_pipeline(
        files,
        output_dir=args.output_dir,
        topic_taxonomy_path=args.topic_taxonomy,
        notifier=notifier,
        **run_kwargs,
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
