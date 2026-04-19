"""Stage summarization for KnowledgeHarness."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List


CATEGORIES = [
    "basic_concepts",
    "methods_and_processes",
    "examples_and_applications",
    "difficult_or_error_prone_points",
    "extended_reading",
    "unclassified",
]


def stage_summarize(documents: List[Dict[str, Any]], classified: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Generate 3-stage baseline summaries."""
    source_count = len(documents)

    theme_counter = Counter()
    for cat in CATEGORIES:
        theme_counter[cat] = len(classified.get(cat, []))

    missing_themes = [k for k, v in theme_counter.items() if v == 0 and k != "unclassified"]

    stage_1 = {
        "name": "Stage 1: Overview",
        "source_count": source_count,
        "theme_distribution": dict(theme_counter),
        "potentially_missing_themes": missing_themes,
        "summary_text": (
            f"Processed {source_count} sources. "
            f"Top theme counts: {dict(theme_counter)}. "
            f"Potentially missing themes: {missing_themes or 'none'}."
        ),
    }

    category_summaries = {}
    for cat in CATEGORIES:
        items = classified.get(cat, [])
        preview = [i.get("chunk_text", "")[:120] for i in items[:3]]
        category_summaries[cat] = {
            "count": len(items),
            "preview": preview,
        }

    stage_2 = {
        "name": "Stage 2: Category Summary",
        "categories": category_summaries,
    }

    stage_3 = {
        "name": "Stage 3: Final Key Notes",
        "must_remember_concepts": [c.get("chunk_text", "") for c in classified.get("basic_concepts", [])[:5]],
        "high_priority_points": [c.get("chunk_text", "") for c in classified.get("methods_and_processes", [])[:5]],
        "easy_to_confuse_points": [
            c.get("chunk_text", "") for c in classified.get("difficult_or_error_prone_points", [])[:5]
        ],
        "next_reading_directions": [c.get("chunk_text", "") for c in classified.get("extended_reading", [])[:5]],
    }

    return {"stage_1": stage_1, "stage_2": stage_2, "stage_3": stage_3}


if __name__ == "__main__":
    import json

    print(
        json.dumps(
            stage_summarize([], {k: [] for k in CATEGORIES}),
            ensure_ascii=False,
            indent=2,
        )
    )
