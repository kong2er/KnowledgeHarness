"""Minimal CLI app to run KnowledgeHarness MVP pipeline."""

from __future__ import annotations

import argparse
import glob
from pathlib import Path
from typing import List

from tools.chunk_notes import chunk_notes
from tools.classify_notes import classify_notes
from tools.export_notes import export_notes
from tools.extract_keypoints import extract_keypoints
from tools.parse_inputs import parse_inputs
from tools.stage_summarize import stage_summarize
from tools.validate_result import validate_result

# Directories that are part of the project itself; when the user points
# app.py at a parent directory we skip these to avoid treating project
# documentation as user study material.
EXCLUDED_DIR_NAMES = {
    "outputs",
    "docs",
    "project_memory",
    ".codex",
    ".git",
    "__pycache__",
    ".venv",
}


def _is_under_excluded_dir(path: Path) -> bool:
    return any(part in EXCLUDED_DIR_NAMES for part in path.parts)


def collect_input_files(inputs: List[str]) -> List[str]:
    """Collect file paths from explicit files, directories, and glob patterns.

    Project-meta directories (docs/, outputs/, project_memory/, .codex/, .git/)
    are filtered out automatically so running the pipeline on the project
    root never pulls in our own documentation as "user material".
    Explicit single-file arguments are always honored.
    """
    files: List[str] = []
    for item in inputs:
        p = Path(item)
        if p.is_dir():
            if p.name in EXCLUDED_DIR_NAMES:
                continue
            for ext in ("*.txt", "*.md", "*.pdf"):
                for f in p.glob(ext):
                    if _is_under_excluded_dir(f):
                        continue
                    files.append(str(f))
        else:
            matches = glob.glob(item)
            if matches:
                for m in matches:
                    mp = Path(m)
                    if _is_under_excluded_dir(mp):
                        continue
                    files.append(m)
            elif p.exists() and p.is_file():
                # Explicit file arguments are accepted unconditionally.
                files.append(str(p))

    # Stable unique order.
    deduped: List[str] = []
    seen = set()
    for f in files:
        key = str(Path(f).resolve())
        if key not in seen:
            seen.add(key)
            deduped.append(f)
    return deduped


def run_pipeline(input_files: List[str], output_dir: str = "outputs") -> dict:
    parsed = parse_inputs(input_files)
    documents = parsed["documents"]
    logs = parsed.get("logs", {}) or {}
    failed_sources = logs.get("failed_sources", []) or []
    empty_sources = logs.get("empty_extracted_sources", []) or []

    chunks = chunk_notes(documents)
    classified_output = classify_notes(chunks)

    # Must classify before summarize.
    summaries = stage_summarize(documents, classified_output["categorized"])
    keypoints = extract_keypoints(classified_output["categorized"])

    # MVP: external resources placeholder (user content remains primary).
    # Expected schema once enrichment lands: title / url / purpose / relevance_reason.
    web_resources: List[dict] = []

    validation = validate_result(
        classified_output,
        summaries,
        failed_sources=failed_sources,
        empty_sources=empty_sources,
    )

    # review_needed stays chunk-level only; system-level signals go to
    # pipeline_notes so the two concerns do not cross-contaminate.
    review_needed = list(classified_output.get("review_needed", []))
    pipeline_notes: List[str] = []
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
        },
        "source_documents": documents,
        "categorized_notes": classified_output["categorized"],
        "stage_summaries": summaries,
        "key_points": keypoints,
        "web_resources": web_resources,
        "review_needed": review_needed,
        "pipeline_notes": pipeline_notes,
        "validation": validation,
    }

    export_paths = export_notes(result, out_dir=output_dir)
    result["export_paths"] = export_paths
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="KnowledgeHarness MVP")
    parser.add_argument("inputs", nargs="+", help="Input files / dirs / globs")
    parser.add_argument("--output-dir", default="outputs", help="Output directory")
    args = parser.parse_args()

    files = collect_input_files(args.inputs)
    if not files:
        raise SystemExit("No valid input files found.")

    result = run_pipeline(files, output_dir=args.output_dir)
    validation = result.get("validation", {}) or {}
    print("Pipeline completed.")
    print(f"JSON: {result['export_paths']['json_path']}")
    print(f"MD:   {result['export_paths']['md_path']}")
    print(f"is_valid: {validation.get('is_valid')}")
    warnings = validation.get("warnings") or []
    print(f"warnings: {warnings if warnings else '(none)'}")


if __name__ == "__main__":
    main()
