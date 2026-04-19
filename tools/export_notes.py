"""Exporters for KnowledgeHarness outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List


def _emit_list(lines: List[str], title: str, items: Iterable[str]) -> None:
    items = list(items or [])
    lines.append(f"- **{title}**")
    if not items:
        lines.append("  - (none)")
        return
    for t in items:
        lines.append(f"  - {t}")


def _render_markdown(result: Dict[str, Any]) -> str:
    overview = result.get("overview", {}) or {}
    categorized = result.get("categorized_notes", {}) or {}
    summaries = result.get("stage_summaries", {}) or {}
    key_points = (result.get("key_points", {}) or {}).get("key_points", []) or []
    web_resources = result.get("web_resources", []) or []
    review_needed = result.get("review_needed", []) or []
    pipeline_notes = result.get("pipeline_notes", []) or []
    validation = result.get("validation", {}) or {}
    failed_sources = overview.get("failed_sources", []) or []
    empty_sources = overview.get("empty_extracted_sources", []) or []

    lines: List[str] = [
        "# KnowledgeHarness Result",
        "",
        "## Overview",
        f"- Source count: {overview.get('source_count', 0)}",
        f"- Chunk count: {overview.get('chunk_count', 0)}",
    ]
    if failed_sources:
        lines.append(f"- Failed sources: {len(failed_sources)}")
    if empty_sources:
        lines.append(f"- Empty extracted sources: {len(empty_sources)}")

    lines += ["", "## Categorized Notes"]
    for cat, items in categorized.items():
        lines.append(f"### {cat}")
        if not items:
            lines.append("- (empty)")
            lines.append("")
            continue
        for i in items:
            conf = i.get("confidence", 0)
            lines.append(
                f"- [{i.get('chunk_id')}] ({i.get('source_name')}) "
                f"conf={conf} {i.get('chunk_text', '')[:180]}"
            )
        lines.append("")

    # --- Stage Summaries ---
    s1 = summaries.get("stage_1", {}) or {}
    s2 = summaries.get("stage_2", {}) or {}
    s3 = summaries.get("stage_3", {}) or {}

    lines += [
        "## Stage Summaries",
        "### Stage 1: Overview",
        f"- {s1.get('summary_text', '')}",
    ]
    theme_dist = s1.get("theme_distribution", {}) or {}
    if theme_dist:
        lines.append("- Theme distribution:")
        for k, v in theme_dist.items():
            lines.append(f"  - {k}: {v}")
    missing_themes = s1.get("potentially_missing_themes", []) or []
    if missing_themes:
        lines.append(f"- Potentially missing themes: {', '.join(missing_themes)}")

    lines.append("### Stage 2: Category Summary")
    s2_cats = s2.get("categories", {}) or {}
    if not s2_cats:
        lines.append("- (empty)")
    else:
        for cat_name, data in s2_cats.items():
            lines.append(f"- **{cat_name}** (count={data.get('count', 0)})")
            for preview in data.get("preview", []) or []:
                lines.append(f"  - {preview}")

    lines.append("### Stage 3: Final Key Notes")
    _emit_list(lines, "Must remember", s3.get("must_remember_concepts", []))
    _emit_list(lines, "High priority", s3.get("high_priority_points", []))
    _emit_list(lines, "Easy to confuse", s3.get("easy_to_confuse_points", []))
    _emit_list(lines, "Next reading", s3.get("next_reading_directions", []))

    # --- Key points ---
    lines += ["", "## Key Points"]
    if not key_points:
        lines.append("- (none)")
    else:
        for p in key_points:
            lines.append(f"- {p}")

    # --- Web resources (supplementary, not primary) ---
    lines += ["", "## Web Resources (Supplementary)"]
    if not web_resources:
        lines.append("- (none)")
    else:
        for w in web_resources:
            relevance = w.get("relevance_reason", w.get("reason", ""))
            lines.append(
                f"- [{w.get('title')}]({w.get('url')}) - "
                f"{w.get('purpose')} ({relevance})"
            )

    # --- Failed / empty sources (traceability) ---
    if failed_sources:
        lines += ["", "## Failed Sources"]
        for f in failed_sources:
            lines.append(f"- {f.get('source')}: {f.get('error')}")

    if empty_sources:
        lines += ["", "## Empty Extracted Sources"]
        for e in empty_sources:
            lines.append(f"- {e}")

    # --- Review needed (chunk-level only) ---
    lines += ["", "## Review Needed"]
    if not review_needed:
        lines.append("- (none)")
    else:
        for r in review_needed:
            lines.append(
                f"- [{r.get('chunk_id')}] ({r.get('source_name')}) "
                f"{r.get('reason')} | {r.get('detail', '')}"
            )

    # --- Pipeline notes (system-level signals, separated from review_needed) ---
    lines += ["", "## Pipeline Notes"]
    if not pipeline_notes:
        lines.append("- (none)")
    else:
        for note in pipeline_notes:
            lines.append(f"- {note}")

    # --- Validation summary ---
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
