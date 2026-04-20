"""Rule-based chunk classification for KnowledgeHarness.

Classification policy (acceptance baseline):
- Only emit labels from CATEGORIES.
- Tie-break by CATEGORY_PRIORITY instead of dropping to `unclassified`;
  confidence is penalized so ambiguous items still surface in review_needed.
- A leading "label phrase" (e.g. "概念：", "易错点：") gives a strong bonus
  because that mirrors how real study notes are authored.
- Chunks with zero keyword hits fall into `unclassified` and review_needed.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple, Optional

CATEGORIES = [
    "basic_concepts",
    "methods_and_processes",
    "examples_and_applications",
    "difficult_or_error_prone_points",
    "extended_reading",
    "unclassified",
]

# Priority order used when multiple categories tie on score.
# Rationale: explicit "pitfall" and "reading" markers are the most unambiguous
# signals users leave in notes, so they beat the broader method/example/concept
# buckets during a tie-break.
CATEGORY_PRIORITY = [
    "difficult_or_error_prone_points",
    "extended_reading",
    "methods_and_processes",
    "examples_and_applications",
    "basic_concepts",
]

KEYWORDS: Dict[str, List[str]] = {
    "basic_concepts": [
        "定义", "概念", "本质", "是什么", "原理", "含义",
        "definition", "concept", "principle",
    ],
    "methods_and_processes": [
        "步骤", "流程", "方法", "算法", "过程", "实现",
        "how to", "process", "method", "procedure", "algorithm",
    ],
    "examples_and_applications": [
        "例如", "例子", "案例", "应用", "场景", "实战", "举例", "demo",
        "example", "application", "case",
    ],
    "difficult_or_error_prone_points": [
        "易错", "难点", "注意", "陷阱", "坑", "常见错误", "误区",
        "warning", "pitfall", "caveat", "gotcha",
    ],
    "extended_reading": [
        "扩展阅读", "延伸阅读", "参考", "参考资料", "链接", "论文", "官方",
        "read more", "resource", "reference", "further reading",
        "http://", "https://",
    ],
}

# Label hints are matched against the leading "xxx：" prefix only.
# A chunk starting with "概念：..." is a much stronger signal than the same
# keyword appearing somewhere inside a long paragraph.
LABEL_HINTS: Dict[str, List[str]] = {
    "basic_concepts": ["概念", "定义", "本质", "原理"],
    "methods_and_processes": ["方法", "步骤", "流程", "过程"],
    "examples_and_applications": ["例如", "例子", "案例", "应用", "举例", "实战"],
    "difficult_or_error_prone_points": ["易错", "难点", "注意", "坑", "陷阱", "误区"],
    "extended_reading": ["扩展阅读", "延伸阅读", "参考"],
}

# Match a short "label" that precedes a Chinese or ASCII colon at chunk start,
# tolerating leading markdown heading marks (# / ## / ...).
_LABEL_RE = re.compile(r"^\s*#*\s*([^\s：:]{2,8})\s*[：:]")


def _leading_label(text: str) -> str | None:
    match = _LABEL_RE.match(text or "")
    return match.group(1) if match else None


def _score_chunk(
    chunk_text: str,
    keywords: Dict[str, List[str]],
    label_hints: Dict[str, List[str]],
) -> Dict[str, int]:
    text_lower = (chunk_text or "").lower()
    scores = {k: 0 for k in keywords}

    # Body-level keyword matching (weak evidence, +1 per hit).
    for category, words in keywords.items():
        for w in words:
            if w.lower() in text_lower:
                scores[category] += 1

    # Leading-label matching (strong evidence, +3 once per category).
    label = _leading_label(chunk_text or "")
    if label:
        for category, hints in label_hints.items():
            for hint in hints:
                if hint in label:
                    scores[category] += 3
                    break  # cap: at most one label bonus per category

    return scores


def _priority_of(category: str, category_priority: List[str]) -> int:
    try:
        return category_priority.index(category)
    except ValueError:
        return len(category_priority)


def _choose_category(
    scores: Dict[str, int],
    category_priority: List[str],
) -> Tuple[str, float, str]:
    # Sort: higher score first; break ties by category priority.
    ordered = sorted(
        scores.items(),
        key=lambda item: (-item[1], _priority_of(item[0], category_priority)),
    )
    best_cat, best_score = ordered[0]
    second_score = ordered[1][1] if len(ordered) > 1 else 0

    if best_score <= 0:
        return "unclassified", 0.0, "no keyword matched"

    # Stepped confidence. A body-only single hit (score=1) barely passes the
    # review_needed threshold (0.4), while a label-hit (>=3) is trusted.
    if best_score >= 4:
        confidence = 1.0
    elif best_score == 3:
        confidence = 0.85
    elif best_score == 2:
        confidence = 0.6
    else:
        confidence = 0.4

    if best_score == second_score:
        # Tie: keep the priority-elected category, but flag for review.
        return best_cat, confidence * 0.75, "tie resolved by category priority"

    return best_cat, confidence, "rule-based keyword match"


def classify_notes(
    chunks: List[Dict[str, Any]],
    keywords: Optional[Dict[str, List[str]]] = None,
    label_hints: Optional[Dict[str, List[str]]] = None,
    category_priority: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Classify chunks and produce review_needed for low-confidence items."""
    keywords = keywords or KEYWORDS
    label_hints = label_hints or LABEL_HINTS
    category_priority = category_priority or CATEGORY_PRIORITY

    categorized: Dict[str, List[Dict[str, Any]]] = {c: [] for c in CATEGORIES}
    review_needed: List[Dict[str, Any]] = []
    enriched_chunks: List[Dict[str, Any]] = []

    for chunk in chunks:
        text = chunk.get("chunk_text", "")
        scores = _score_chunk(text, keywords=keywords, label_hints=label_hints)
        category, confidence, reason = _choose_category(
            scores,
            category_priority=category_priority,
        )

        item = {
            **chunk,
            "category": category,
            "confidence": round(confidence, 3),
            "classification_reason": reason,
            "keyword_scores": scores,
        }
        if category not in categorized:
            item["category"] = "unclassified"
            item["classification_reason"] = "out-of-scope category normalized"
            item["confidence"] = 0.0
            category = "unclassified"
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
