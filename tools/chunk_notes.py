"""Chunking utilities for KnowledgeHarness."""

from __future__ import annotations

import re
from typing import Any, Dict, List


PARA_SPLIT_RE = re.compile(r"\n\s*\n+")


def _split_long_paragraph(text: str, max_chars: int = 500) -> List[str]:
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []

    chunks: List[str] = []
    current = ""
    for sentence in re.split(r"(?<=[。！？.!?])\s+", text):
        if not sentence:
            continue
        if len(current) + len(sentence) + 1 <= max_chars:
            current = f"{current} {sentence}".strip()
        else:
            if current:
                chunks.append(current)
            current = sentence.strip()
    if current:
        chunks.append(current)
    return chunks


def chunk_notes(documents: List[Dict[str, Any]], max_chars: int = 500) -> List[Dict[str, Any]]:
    """Split documents into semantic chunks by paragraph + length rules."""
    all_chunks: List[Dict[str, Any]] = []

    for doc_idx, doc in enumerate(documents):
        extracted_text = (doc.get("extracted_text") or "").strip()
        if not extracted_text:
            continue

        paragraphs = [p.strip() for p in PARA_SPLIT_RE.split(extracted_text) if p.strip()]
        local_idx = 0

        for para in paragraphs:
            for piece in _split_long_paragraph(para, max_chars=max_chars):
                chunk = {
                    "chunk_id": f"{doc_idx:03d}-{local_idx:04d}",
                    "source_name": doc.get("source_name"),
                    "source_type": doc.get("source_type"),
                    "source_path": doc.get("source_path"),
                    "raw_text": doc.get("raw_text", ""),
                    "extracted_text": doc.get("extracted_text", ""),
                    "chunk_text": piece,
                }
                all_chunks.append(chunk)
                local_idx += 1

    return all_chunks


if __name__ == "__main__":
    import json

    sample_docs = [
        {
            "source_name": "sample.md",
            "source_type": "md",
            "source_path": "sample.md",
            "raw_text": "概念A\n\n方法B。",
            "extracted_text": "概念A\n\n方法B。",
        }
    ]
    print(json.dumps(chunk_notes(sample_docs), ensure_ascii=False, indent=2))
