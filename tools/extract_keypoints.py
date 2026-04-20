"""Key point extraction for KnowledgeHarness.

Ordering policy:
- Iterate categories in review priority (pitfalls first, then concepts,
  methods, examples).
- Within each category, sort candidates by ``confidence`` descending so
  high-confidence chunks always rank ahead of tie-broken items.
- Deduplicate on normalized text.
- Keep only the top ``max_points`` entries.
"""

from __future__ import annotations

from typing import Any, Dict, List

# Category iteration order for key-point assembly. Pitfalls come first so
# that "things to be careful about" always surface ahead of methods/examples
# when space is tight (max_points cap).
BUCKET_ORDER = [
    "difficult_or_error_prone_points",
    "basic_concepts",
    "methods_and_processes",
    "examples_and_applications",
]


def _dedup_texts(texts: List[str]) -> List[str]:
    seen = set()
    output: List[str] = []
    for t in texts:
        key = " ".join(t.split()).lower()
        if key and key not in seen:
            seen.add(key)
            output.append(t)
    return output


def extract_keypoints(
    categorized: Dict[str, List[Dict[str, Any]]],
    max_points: int = 12,
    min_confidence: float = 0.0,
) -> Dict[str, Any]:
    """Extract compact review key points from categorized chunks."""
    ordered_texts: List[str] = []
    threshold = max(0.0, float(min_confidence))
    for cat in BUCKET_ORDER:
        bucket = categorized.get(cat, []) or []
        # Sort by confidence descending; ties keep original order.
        sorted_bucket = sorted(
            bucket,
            key=lambda item: item.get("confidence", 0.0),
            reverse=True,
        )
        for x in sorted_bucket:
            if float(x.get("confidence", 0.0)) < threshold:
                continue
            text = x.get("chunk_text", "")
            if text:
                ordered_texts.append(text)

    merged = _dedup_texts(ordered_texts)
    top_points = merged[:max_points]

    return {
        "key_points": top_points,
        "stats": {
            "total_candidates": len(merged),
            "selected": len(top_points),
            "min_confidence": threshold,
        },
    }


if __name__ == "__main__":
    import json

    print(json.dumps(extract_keypoints({}), ensure_ascii=False, indent=2))
