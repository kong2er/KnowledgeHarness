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
    web_resources: Optional[List[Dict[str, Any]]] = None,
    web_enrichment_enabled: bool = False,
    semantic_conflicts: Optional[List[Dict[str, Any]]] = None,
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
        web_resources: Optional enrichment resources.
        web_enrichment_enabled: Whether enrichment checks should be enforced.
        semantic_conflicts: Optional semantic conflict records.
    """
    failed_sources = failed_sources or []
    empty_sources = empty_sources or []
    web_resources = web_resources or []
    semantic_conflicts = semantic_conflicts or []

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

    if web_enrichment_enabled:
        missing_url = sum(1 for item in web_resources if not (item or {}).get("url"))
        if missing_url > 0:
            warnings.append(f"web_resources_missing_url:{missing_url}")
        missing_relevance = sum(
            1 for item in web_resources if not (item or {}).get("relevance_reason")
        )
        if missing_relevance > 0:
            warnings.append(f"web_resources_missing_relevance_reason:{missing_relevance}")

    if semantic_conflicts:
        warnings.append(f"semantic_conflicts_detected:{len(semantic_conflicts)}")

    return {
        "is_valid": len(warnings) == 0,
        "warnings": warnings,
        "stats": {
            **stats,
            "duplicate_chunk_ids": duplicated_ids,
            "failed_sources_count": len(failed_sources),
            "empty_sources_count": len(empty_sources),
            "web_resources_count": len(web_resources),
            "semantic_conflict_count": len(semantic_conflicts),
        },
    }


if __name__ == "__main__":
    import json

    print(json.dumps(validate_result({}, {}), ensure_ascii=False, indent=2))
