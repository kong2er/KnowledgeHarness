"""Exporters for KnowledgeHarness outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


def _emit_list(lines: List[str], title: str, items: Iterable[str]) -> None:
    items = list(items or [])
    lines.append(f"- **{title}**")
    if not items:
        lines.append("  - (none)")
        return
    for t in items:
        lines.append(f"  - {t}")


def _render_markdown(result: Dict[str, Any], markdown_use_details: bool = False) -> str:
    overview = result.get("overview", {}) or {}
    categorized = result.get("categorized_notes", {}) or {}
    topic_output = result.get("topic_classification", {}) or {}
    summaries = result.get("stage_summaries", {}) or {}
    key_points = (result.get("key_points", {}) or {}).get("key_points", []) or []
    web_resources = result.get("web_resources", []) or []
    semantic_conflicts = result.get("semantic_conflicts", []) or []
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

    topic_stats = topic_output.get("stats", {}) or {}
    topic_items = topic_output.get("items", []) or []
    topic_mode = topic_output.get("mode_requested", "auto")
    lines += [
        "",
        "## Topic Overview",
        f"- Mode requested: {topic_mode}",
        f"- Classified documents: {topic_stats.get('document_count', len(topic_items))}",
        f"- API-assisted decisions: {topic_stats.get('used_api_count', 0)}",
        f"- Degraded decisions: {topic_stats.get('degraded_count', 0)}",
    ]
    counts_by_label = topic_stats.get("counts_by_label", {}) or {}
    if counts_by_label:
        lines.append("- Counts by topic label:")
        for label, count in counts_by_label.items():
            lines.append(f"  - {label}: {count}")
    if topic_items:
        lines.append("- Per-source topic labels:")
        for item in topic_items:
            lines.append(
                f"  - {item.get('source_name')} -> {item.get('topic_label')} "
                f"(conf={item.get('confidence')}, api={item.get('used_api')})"
            )

    # --- Ingestion summary (input-layer self-report) ---
    ingestion = overview.get("ingestion_summary") or {}
    if ingestion:
        lines += [
            "",
            "## Ingestion Summary",
            f"- Detected: {ingestion.get('detected', 0)}",
            f"- Supported: {ingestion.get('supported', 0)}",
            f"- Unsupported: {ingestion.get('unsupported', 0)}",
            f"- Succeeded: {ingestion.get('succeeded', 0)}",
            f"- Empty extracted: {ingestion.get('empty_extracted', 0)}",
            f"- Failed: {ingestion.get('failed', 0)}",
            f"- OCR backend: {ingestion.get('ocr_backend', 'unavailable')}",
        ]
        eff = ingestion.get("supported_extensions_effective") or []
        if eff:
            lines.append(f"- Effective supported extensions: {', '.join(eff)}")
        opt_in = ingestion.get("image_extensions_opt_in") or []
        if opt_in:
            lines.append(f"- Image extensions (opt-in OCR): {', '.join(opt_in)}")
        breakdown = ingestion.get("breakdown_by_type") or {}
        if breakdown:
            lines.append("- Breakdown by type:")
            for k, v in breakdown.items():
                lines.append(f"  - {k}: {v}")

    lines += ["", "## Categorized Notes"]
    for cat, items in categorized.items():
        if markdown_use_details:
            lines.append(f"<details><summary>{cat} (count={len(items)})</summary>")
        else:
            lines.append(f"### {cat}")
        if not items:
            lines.append("- (empty)")
            if markdown_use_details:
                lines.append("</details>")
            lines.append("")
            continue
        for i in items:
            conf = i.get("confidence", 0)
            lines.append(
                f"- [{i.get('chunk_id')}] ({i.get('source_name')}) "
                f"conf={conf} {i.get('chunk_text', '')[:180]}"
            )
        if markdown_use_details:
            lines.append("</details>")
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
            reason = f.get("reason") or "parse_error"
            lines.append(
                f"- {f.get('source')} [{reason}]: {f.get('error', '')}"
            )

    if empty_sources:
        lines += ["", "## Empty Extracted Sources"]
        for e in empty_sources:
            lines.append(f"- {e}")

    if semantic_conflicts:
        lines += ["", "## Semantic Conflicts (Heuristic)"]
        for c in semantic_conflicts:
            a = c.get("chunk_a", {}) or {}
            b = c.get("chunk_b", {}) or {}
            lines.append(
                f"- {c.get('reason')} | "
                f"{a.get('chunk_id')} vs {b.get('chunk_id')}"
            )

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


import re as _re

# Leading category marker like "概念：" / "方法步骤：" / "例如：" / "易错点：" /
# "扩展阅读：" that the classifier uses as a strong signal. In the final
# notes markdown, the section header already tells the reader *what* the
# entry is, so repeating this prefix is pure noise.
_LEADING_CATEGORY_PREFIX_RE = _re.compile(
    r"^\s*(?:"
    r"概念|定义|本质|原理|含义|"
    r"方法步骤|方法|步骤|流程|过程|实现|"
    r"例如|例子|案例|应用|场景|实战|举例|demo|"
    r"易错点|易错|难点|注意事项|注意|陷阱|坑|常见错误|误区|"
    r"扩展阅读|延伸阅读|参考资料|参考|延伸"
    r")\s*[:：]\s*",
    flags=_re.IGNORECASE,
)

# Trailing "[heading_path: xxx > yyy]" marker that `parse_inputs._read_docx_file`
# injects to give the downstream classifier awareness of the document's
# outline. It is an *intermediate* signal and must not appear in the final
# human-facing notes.
_TRAILING_HEADING_PATH_RE = _re.compile(
    r"\s*\[heading_path:\s*[^\]]+\]\s*$",
    flags=_re.IGNORECASE,
)


def _clean_note_text(text: str) -> str:
    """Strip classifier-facing noise from a chunk before rendering as a note."""
    t = (text or "").strip()
    if not t:
        return ""
    t = _LEADING_CATEGORY_PREFIX_RE.sub("", t, count=1)
    t = _TRAILING_HEADING_PATH_RE.sub("", t)
    return t.strip()


def _format_topic_summary(
    topic_items: List[Dict[str, Any]],
    label_definitions: List[Dict[str, Any]],
) -> List[str]:
    """Return markdown bullet lines describing the topic distribution.

    - uses `display_name` from the taxonomy instead of raw label_id
    - deduplicates and counts when multiple sources share a topic
    - single-source documents still render as "- <display>"
    """
    display_map = {
        str(item.get("label_id", "")): str(item.get("display_name") or item.get("label_id") or "")
        for item in (label_definitions or [])
    }

    counts: Dict[str, int] = {}
    for it in topic_items:
        label = str(it.get("topic_label") or "unknown_topic")
        counts[label] = counts.get(label, 0) + 1

    if not counts:
        return ["- 未归类"]

    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    lines: List[str] = []
    for label, n in ordered:
        display = display_map.get(label) or label
        if label == "unknown_topic":
            display = "未归类"
        suffix = f"（{n} 份）" if n > 1 else ""
        lines.append(f"- {display}{suffix}")
    return lines


def _render_final_notes_markdown(result: Dict[str, Any]) -> str:
    """Render a note-first markdown without pipeline diagnostics.

    Layout rules (why the output looks the way it does):
    - No "概念：/ 方法：..." prefix: the section header already says it.
    - No "[heading_path: ...]" tail: that's a classifier-only marker.
    - Source is annotated only when more than one source contributed.
    - "重点速记" only surfaces when there are enough notes that a
      top-N distillation is actually useful; otherwise omitted to avoid
      "speed recall" being a verbatim copy of every preceding section.
    """
    topic_output = result.get("topic_classification", {}) or {}
    topic_items = topic_output.get("items", []) or []
    label_definitions = topic_output.get("label_definitions", []) or []

    categorized = result.get("categorized_notes", {}) or {}
    stage3 = (result.get("stage_summaries", {}) or {}).get("stage_3", {}) or {}
    key_points_raw = (result.get("key_points", {}) or {}).get("key_points", []) or []
    overview = result.get("overview", {}) or {}

    # A source appears "multi" only if >1 distinct source_name contributed
    # note content. We key off the topic items (document-level records)
    # because they are guaranteed to cover each ingested source exactly once.
    source_names = {
        str(it.get("source_name") or "") for it in topic_items if it.get("source_name")
    }
    multi_source = len(source_names) > 1

    def _cat_rows(cat: str) -> List[Tuple[str, str]]:
        rows = categorized.get(cat, []) or []
        out: List[Tuple[str, str]] = []
        for r in rows:
            text = _clean_note_text(r.get("chunk_text") or "")
            if not text:
                continue
            src = str(r.get("source_name") or "")
            out.append((text, src))
        return out

    def _fallback_rows(stage3_key: str) -> List[Tuple[str, str]]:
        items = stage3.get(stage3_key, []) or []
        return [(_clean_note_text(t), "") for t in items if _clean_note_text(t)]

    def _emit(header: str, rows: List[Tuple[str, str]]) -> None:
        lines.append("")
        lines.append(header)
        if not rows:
            lines.append("- （无）")
            return
        for text, source in rows:
            if multi_source and source:
                lines.append(f"- {text} *（来源：{source}）*")
            else:
                lines.append(f"- {text}")

    concepts = _cat_rows("basic_concepts")
    methods = _cat_rows("methods_and_processes")
    examples = _cat_rows("examples_and_applications")
    pitfalls = _cat_rows("difficult_or_error_prone_points")
    reading = _cat_rows("extended_reading") or _fallback_rows("next_reading_directions")

    lines: List[str] = ["# 整理笔记"]

    # --- Overview (only when multi-source, otherwise skip to reduce clutter) ---
    if multi_source:
        lines.append("")
        lines.append(
            f"> 本笔记由 {len(source_names)} 份文档合并整理而成："
            + "、".join(sorted(source_names))
        )

    # --- Topic ---
    lines += ["", "## 主题"]
    lines.extend(_format_topic_summary(topic_items, label_definitions))

    _emit("## 核心概念", concepts)
    _emit("## 方法步骤", methods)
    _emit("## 例子与应用", examples)
    _emit("## 易错点", pitfalls)
    _emit("## 延伸阅读", reading)

    # --- Key-point distillation ---
    # Only surface "重点速记" when the main sections are rich enough for
    # distillation to add information. Otherwise it's a verbatim echo.
    total_main = len(concepts) + len(methods) + len(examples) + len(pitfalls) + len(reading)
    if total_main > 12 and key_points_raw:
        def _norm(s: str) -> str:
            return " ".join(_clean_note_text(s).split()).lower()
        shown = {_norm(text) for text, _ in concepts + methods + examples + pitfalls + reading}
        distilled: List[str] = []
        for p in key_points_raw:
            clean = _clean_note_text(p)
            if not clean:
                continue
            if _norm(clean) in shown:
                continue
            distilled.append(clean)
        if distilled:
            lines += ["", "## 重点速记"]
            lines.extend([f"- {x}" for x in distilled[:6]])

    # --- Footer with minimal provenance ---
    lines += [
        "",
        "---",
        f"*共整理 {total_main} 条笔记，来自 {overview.get('source_count', 0)} 份文档。*",
    ]

    return "\n".join(lines).strip() + "\n"


def export_notes(
    result: Dict[str, Any],
    out_dir: str | Path = "outputs",
    markdown_use_details: bool = False,
    final_notes_only: bool = False,
) -> Dict[str, str]:
    """Export result as JSON + Markdown files."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    json_path = out / "result.json"
    md_path = out / "result.md"

    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if final_notes_only:
        md_text = _render_final_notes_markdown(result)
    else:
        md_text = _render_markdown(result, markdown_use_details=markdown_use_details)
    md_path.write_text(md_text, encoding="utf-8")

    return {
        "json_path": str(json_path.resolve()),
        "md_path": str(md_path.resolve()),
    }


if __name__ == "__main__":
    print(export_notes({"overview": {}}, out_dir="outputs"))
