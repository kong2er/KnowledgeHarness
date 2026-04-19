"""Input parsing utilities for KnowledgeHarness.

Supports txt / md / pdf and returns a unified document structure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf"}


def _read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _read_pdf_file(path: Path) -> str:
    # Lazy import so txt/md can still run without PDF dependency installed.
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as exc:
        raise RuntimeError("PDF parsing requires 'pypdf'. Run: pip install -r requirements.txt") from exc

    reader = PdfReader(str(path))
    pages: List[str] = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n\n".join(pages).strip()


def parse_single_file(path: str | Path) -> Dict[str, Any]:
    """Parse one file into a normalized document object."""
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"Input file not found: {file_path}")

    ext = file_path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {file_path.name}")

    if ext in {".txt", ".md"}:
        extracted = _read_text_file(file_path)
    else:
        extracted = _read_pdf_file(file_path)

    return {
        "source_name": file_path.name,
        "source_path": str(file_path.resolve()),
        "source_type": ext.lstrip("."),
        "chunk_id": None,
        "raw_text": extracted,
        "extracted_text": extracted,
    }


def parse_inputs(paths: Iterable[str | Path]) -> Dict[str, Any]:
    """Parse multiple input files.

    Returns:
        {
          "documents": [...],
          "logs": {"failed_sources": [...]}
        }
    """
    documents: List[Dict[str, Any]] = []
    failed_sources: List[Dict[str, str]] = []

    for path in paths:
        try:
            documents.append(parse_single_file(path))
        except Exception as exc:  # keep pipeline resilient
            failed_sources.append({"source": str(path), "error": str(exc)})

    return {
        "documents": documents,
        "logs": {"failed_sources": failed_sources},
    }


if __name__ == "__main__":
    import json
    import sys

    parsed = parse_inputs(sys.argv[1:])
    print(json.dumps(parsed, ensure_ascii=False, indent=2))
