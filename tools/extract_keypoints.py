"""Key point extraction for KnowledgeHarness."""

from __future__ import annotations

from typing import Any, Dict, List


def _dedup_texts(texts: List[str]) -> List[str]:
    seen = set()
    output: List[str] = []
    for t in texts:
        key = " ".join(t.split()).lower()
        if key and key not in seen:
            seen.add(key)
            output.append(t)
    return output


def extract_keypoints(categorized: Dict[str, List[Dict[str, Any]]], max_points: int = 12) -> Dict[str, Any]:
    """Extract compact review key points from categorized chunks."""
    must_remember = [x.get("chunk_text", "") for x in categorized.get("basic_concepts", [])]
    process_points = [x.get("chunk_text", "") for x in categorized.get("methods_and_processes", [])]
    risk_points = [x.get("chunk_text", "") for x in categorized.get("difficult_or_error_prone_points", [])]
    examples = [x.get("chunk_text", "") for x in categorized.get("examples_and_applications", [])]

    merged = _dedup_texts(must_remember + process_points + risk_points + examples)
    top_points = merged[:max_points]

    return {
        "key_points": top_points,
        "stats": {
            "total_candidates": len(merged),
            "selected": len(top_points),
        },
    }


if __name__ == "__main__":
    import json

    print(json.dumps(extract_keypoints({}), ensure_ascii=False, indent=2))
