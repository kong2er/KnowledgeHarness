"""Lightweight semantic conflict detection (rule-based).

This is a minimum heuristic layer. It does not claim full NLI semantics.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

_CLAIM_RE = re.compile(
    r"(?P<subject>.{1,24}?)(?P<kw>必须|不需要|需要|可以|不可以|建议|不建议|启用|禁用|开启|关闭|是|不是)"
)

# Opposite polarity pairs on same extracted subject.
_CONTRADICTIONS = {
    ("must", "no_need"),
    ("need", "no_need"),
    ("allow", "disallow"),
    ("recommend", "not_recommend"),
    ("enable", "disable"),
    ("be_true", "be_false"),
}

_TAG_MAP = {
    "必须": "must",
    "需要": "need",
    "不需要": "no_need",
    "可以": "allow",
    "不可以": "disallow",
    "建议": "recommend",
    "不建议": "not_recommend",
    "启用": "enable",
    "开启": "enable",
    "禁用": "disable",
    "关闭": "disable",
    "是": "be_true",
    "不是": "be_false",
}


def _normalize_subject(subject: str) -> str:
    subject = re.sub(r"[\s\-_:：，。,.!?！？()\[\]{}]+", "", subject or "")
    # keep a bounded key to reduce accidental long-text collisions
    return subject[:20].lower()


def _extract_claim(chunk_text: str) -> Optional[Tuple[str, str, str]]:
    text = (chunk_text or "").strip()
    if not text:
        return None
    m = _CLAIM_RE.search(text)
    if not m:
        return None

    subject = _normalize_subject(m.group("subject"))
    kw = m.group("kw")
    tag = _TAG_MAP.get(kw)
    if not subject or not tag:
        return None
    return subject, tag, kw


def _is_contradiction(a: str, b: str) -> bool:
    return (a, b) in _CONTRADICTIONS or (b, a) in _CONTRADICTIONS


def detect_semantic_conflicts(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Detect potential conflicts from chunk-level claims.

    Returns list of conflict records with chunk references.
    """
    by_subject: Dict[str, List[Dict[str, Any]]] = {}

    for item in chunks:
        claim = _extract_claim(item.get("chunk_text", ""))
        if not claim:
            continue
        subject, tag, kw = claim
        by_subject.setdefault(subject, []).append(
            {
                "chunk_id": item.get("chunk_id"),
                "source_name": item.get("source_name"),
                "tag": tag,
                "keyword": kw,
                "text": item.get("chunk_text", ""),
            }
        )

    conflicts: List[Dict[str, Any]] = []
    seen_pairs = set()

    for subject, claims in by_subject.items():
        n = len(claims)
        if n < 2:
            continue
        for i in range(n):
            for j in range(i + 1, n):
                a = claims[i]
                b = claims[j]
                if not _is_contradiction(a["tag"], b["tag"]):
                    continue
                pair_key = tuple(sorted([str(a["chunk_id"]), str(b["chunk_id"])]))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                conflicts.append(
                    {
                        "subject_key": subject,
                        "reason": f"contradictory claim keywords: {a['keyword']} vs {b['keyword']}",
                        "chunk_a": {
                            "chunk_id": a["chunk_id"],
                            "source_name": a["source_name"],
                            "text": a["text"],
                        },
                        "chunk_b": {
                            "chunk_id": b["chunk_id"],
                            "source_name": b["source_name"],
                            "text": b["text"],
                        },
                    }
                )

    return conflicts


if __name__ == "__main__":
    demo = [
        {"chunk_id": "a", "source_name": "x", "chunk_text": "缓存策略必须开启"},
        {"chunk_id": "b", "source_name": "x", "chunk_text": "缓存策略不需要开启"},
    ]
    import json

    print(json.dumps(detect_semantic_conflicts(demo), ensure_ascii=False, indent=2))
