"""Rule-based chunk classification for KnowledgeHarness."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

CATEGORIES = [
    "basic_concepts",
    "methods_and_processes",
    "examples_and_applications",
    "difficult_or_error_prone_points",
    "extended_reading",
    "unclassified",
]

KEYWORDS: Dict[str, List[str]] = {
    "basic_concepts": ["定义", "概念", "本质", "是什么", "definition", "concept"],
    "methods_and_processes": ["步骤", "流程", "方法", "算法", "how to", "process", "method"],
    "examples_and_applications": ["例如", "案例", "应用", "场景", "example", "application"],
    "difficult_or_error_prone_points": ["易错", "难点", "注意", "陷阱", "warning", "pitfall"],
    "extended_reading": ["参考", "链接", "论文", "官方", "read more", "resource", "http://", "https://"],
}


def _score_chunk(chunk_text: str) -> Dict[str, int]:
    text = chunk_text.lower()
    scores = {k: 0 for k in KEYWORDS}
    for category, words in KEYWORDS.items():
        for w in words:
            if w.lower() in text:
                scores[category] += 1
    return scores


def _choose_category(scores: Dict[str, int]) -> Tuple[str, float, str]:
    ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    best_cat, best_score = ordered[0]
    second_score = ordered[1][1] if len(ordered) > 1 else 0

    if best_score <= 0:
        return "unclassified", 0.0, "no keyword matched"

    confidence = min(1.0, best_score / 3)
    # tie / weak signal -> unclassified
    if best_score == second_score or best_score == 1:
        return "unclassified", confidence * 0.5, "weak or ambiguous keyword signal"

    return best_cat, confidence, "rule-based keyword match"


def classify_notes(chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Classify chunks and produce review_needed for low-confidence items."""
    categorized: Dict[str, List[Dict[str, Any]]] = {c: [] for c in CATEGORIES}
    review_needed: List[Dict[str, Any]] = []
    enriched_chunks: List[Dict[str, Any]] = []

    for chunk in chunks:
        text = chunk.get("chunk_text", "")
        scores = _score_chunk(text)
        category, confidence, reason = _choose_category(scores)

        item = {
            **chunk,
            "category": category,
            "confidence": round(confidence, 3),
            "classification_reason": reason,
            "keyword_scores": scores,
        }
        categorized[category].append(item)
        enriched_chunks.append(item)

        if category == "unclassified" or confidence < 0.4:
            review_needed.append(
                {
                    "chunk_id": item["chunk_id"],
                    "source_name": item.get("source_name"),
                    "reason": "low confidence classification",
                    "detail": reason,
                    "chunk_text": text,
                }
            )

    return {
        "chunks": enriched_chunks,
        "categorized": categorized,
        "review_needed": review_needed,
    }


if __name__ == "__main__":
    import json

    demo = [{"chunk_id": "000-0000", "chunk_text": "这个概念的定义是什么？"}]
    print(json.dumps(classify_notes(demo), ensure_ascii=False, indent=2))
