"""Result validation for KnowledgeHarness."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _normalize(text: str) -> str:
    return " ".join((text or "").split()).strip().lower()


def validate_result(
    classification_output: Dict[str, Any],
    stage_summaries: Dict[str, Any],
    failed_sources: Optional[List[Dict[str, Any]]] = None,
    empty_sources: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Validate classification and summary completeness.

    Args:
        classification_output: Output of ``classify_notes``.
        stage_summaries: Output of ``stage_summarize``.
        failed_sources: Optional list of sources that failed to parse,
            as produced by ``parse_inputs``. When provided, emits a warning
            so downstream consumers can surface the fact.
        empty_sources: Optional list of sources that parsed successfully
            but yielded empty extracted text.
    """
    failed_sources = failed_sources or []
    empty_sources = empty_sources or []

    categorized = classification_output.get("categorized", {})
    all_chunks = classification_output.get("chunks", [])

    warnings: List[str] = []
    stats: Dict[str, Any] = {}

    total = len(all_chunks)
    unclassified_count = len(categorized.get("unclassified", []))
    stats["total_chunks"] = total
    stats["unclassified_chunks"] = unclassified_count

    if total > 0 and (unclassified_count / total) > 0.35:
        warnings.append("too_many_unclassified_chunks")

    empty_major_categories = [
        c
        for c in [
            "basic_concepts",
            "methods_and_processes",
            "examples_and_applications",
            "difficult_or_error_prone_points",
        ]
        if len(categorized.get(c, [])) == 0
    ]
    if empty_major_categories:
        warnings.append(f"empty_major_categories:{','.join(empty_major_categories)}")

    seen: Dict[str, str] = {}
    duplicated_ids: List[str] = []
    for item in all_chunks:
        norm = _normalize(item.get("chunk_text", ""))
        if not norm:
            continue
        if norm in seen:
            duplicated_ids.append(item.get("chunk_id", "unknown"))
        else:
            seen[norm] = item.get("chunk_id")

    if duplicated_ids:
        warnings.append("duplicated_chunks_detected")

    missing_stage_summaries = [k for k in ["stage_1", "stage_2", "stage_3"] if not stage_summaries.get(k)]
    if missing_stage_summaries:
        warnings.append(f"missing_stage_summaries:{','.join(missing_stage_summaries)}")

    if failed_sources:
        warnings.append(f"failed_sources_present:{len(failed_sources)}")

    if empty_sources:
        warnings.append(f"empty_extracted_sources:{len(empty_sources)}")

    return {
        "is_valid": len(warnings) == 0,
        "warnings": warnings,
        "stats": {
            **stats,
            "duplicate_chunk_ids": duplicated_ids,
            "failed_sources_count": len(failed_sources),
            "empty_sources_count": len(empty_sources),
        },
    }


if __name__ == "__main__":
    import json

    print(json.dumps(validate_result({}, {}), ensure_ascii=False, indent=2))
