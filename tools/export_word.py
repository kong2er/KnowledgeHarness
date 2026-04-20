"""Word (.docx) export from markdown output."""

from __future__ import annotations

from pathlib import Path
from typing import List


def _markdown_line_to_paragraph(doc, line: str) -> None:
    s = line.rstrip()
    if not s:
        doc.add_paragraph("")
        return
    if s.startswith("### "):
        doc.add_heading(s[4:].strip(), level=3)
        return
    if s.startswith("## "):
        doc.add_heading(s[3:].strip(), level=2)
        return
    if s.startswith("# "):
        doc.add_heading(s[2:].strip(), level=1)
        return
    if s.startswith("- "):
        doc.add_paragraph(s[2:].strip(), style="List Bullet")
        return
    doc.add_paragraph(s)


def export_word_from_markdown(
    markdown_path: str | Path,
    out_dir: str | Path = "outputs",
    filename: str = "result.docx",
) -> str:
    """Generate a basic docx from markdown text.

    Requires `python-docx` (already part of project requirements).
    """
    from docx import Document  # lazy import

    md_path = Path(markdown_path)
    if not md_path.exists() or not md_path.is_file():
        raise FileNotFoundError(f"markdown file not found: {md_path}")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    docx_path = out / filename

    text = md_path.read_text(encoding="utf-8", errors="replace")
    lines: List[str] = text.splitlines()

    doc = Document()
    for line in lines:
        _markdown_line_to_paragraph(doc, line)
    doc.save(str(docx_path))
    return str(docx_path.resolve())

