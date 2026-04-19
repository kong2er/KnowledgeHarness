"""Exporters for KnowledgeHarness outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


def _render_markdown(result: Dict[str, Any]) -> str:
    overview = result.get("overview", {})
    categorized = result.get("categorized_notes", {})
    summaries = result.get("stage_summaries", {})
    key_points = result.get("key_points", {}).get("key_points", [])
    web_resources = result.get("web_resources", [])
    review_needed = result.get("review_needed", [])
    validation = result.get("validation", {})

    lines = [
        "# KnowledgeHarness Result",
        "",
        "## Overview",
        f"- Source count: {overview.get('source_count', 0)}",
        f"- Chunk count: {overview.get('chunk_count', 0)}",
        "",
        "## Categorized Notes",
    ]

    for cat, items in categorized.items():
        lines.append(f"### {cat}")
        if not items:
            lines.append("- (empty)")
            continue
        for i in items:
            lines.append(
                f"- [{i.get('chunk_id')}] ({i.get('source_name')}) {i.get('chunk_text', '')[:180]}"
            )
        lines.append("")

    lines += [
        "## Stage Summaries",
        "### Stage 1",
        f"- {summaries.get('stage_1', {}).get('summary_text', '')}",
        "### Stage 2",
        f"- Categories covered: {', '.join((summaries.get('stage_2', {}).get('categories', {}) or {}).keys())}",
        "### Stage 3",
    ]
    for t in summaries.get("stage_3", {}).get("must_remember_concepts", [])[:5]:
        lines.append(f"- Must remember: {t}")

    lines += ["", "## Key Points"]
    for p in key_points:
        lines.append(f"- {p}")

    lines += ["", "## Web Resources (Supplementary)"]
    if not web_resources:
        lines.append("- (none)")
    else:
        for w in web_resources:
            lines.append(f"- [{w.get('title')}]({w.get('url')}) - {w.get('purpose')} ({w.get('reason')})")

    lines += ["", "## Review Needed"]
    if not review_needed:
        lines.append("- (none)")
    else:
        for r in review_needed:
            lines.append(f"- [{r.get('chunk_id')}] {r.get('reason')} | {r.get('detail', '')}")

    lines += [
        "",
        "## Validation",
        f"- is_valid: {validation.get('is_valid')}",
        f"- warnings: {validation.get('warnings')}",
    ]

    return "\n".join(lines).strip() + "\n"


def export_notes(result: Dict[str, Any], out_dir: str | Path = "outputs") -> Dict[str, str]:
    """Export result as JSON + Markdown files."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    json_path = out / "result.json"
    md_path = out / "result.md"

    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_render_markdown(result), encoding="utf-8")

    return {
        "json_path": str(json_path.resolve()),
        "md_path": str(md_path.resolve()),
    }


if __name__ == "__main__":
    print(export_notes({"overview": {}}, out_dir="outputs"))
