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


def collect_input_files(inputs: List[str]) -> List[str]:
    """Collect file paths from explicit files, directories, and glob patterns."""
    files: List[str] = []
    for item in inputs:
        p = Path(item)
        if p.is_dir():
            for ext in ("*.txt", "*.md", "*.pdf"):
                files.extend(str(x) for x in p.glob(ext))
        else:
            matches = glob.glob(item)
            if matches:
                files.extend(matches)
            elif p.exists() and p.is_file():
                files.append(str(p))

    # stable unique order
    deduped = []
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

    chunks = chunk_notes(documents)
    classified_output = classify_notes(chunks)

    # Must classify before summarize
    summaries = stage_summarize(documents, classified_output["categorized"])
    keypoints = extract_keypoints(classified_output["categorized"])

    # MVP: external resources placeholder (user content remains primary)
    web_resources = []

    validation = validate_result(classified_output, summaries)

    review_needed = list(classified_output.get("review_needed", []))
    if validation.get("warnings"):
        review_needed.append(
            {
                "chunk_id": "SYSTEM",
                "source_name": "pipeline",
                "reason": "validation warnings",
                "detail": ",".join(validation["warnings"]),
                "chunk_text": "",
            }
        )

    result = {
        "overview": {
            "source_count": len(documents),
            "chunk_count": len(chunks),
            "failed_sources": parsed.get("logs", {}).get("failed_sources", []),
        },
        "source_documents": documents,
        "categorized_notes": classified_output["categorized"],
        "stage_summaries": summaries,
        "key_points": keypoints,
        "web_resources": web_resources,
        "review_needed": review_needed,
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
    print("Pipeline completed.")
    print(f"JSON: {result['export_paths']['json_path']}")
    print(f"MD:   {result['export_paths']['md_path']}")


if __name__ == "__main__":
    main()
