"""最简本地 Web UI（中文界面）.

No third-party UI framework required.
启动:
    python3 service/simple_ui.py --host 127.0.0.1 --port 8765
然后打开:
    http://127.0.0.1:8765

Design constraints (do not regress):
- Never echo API key values back into HTML `value=` attributes; only show a
  "已配置 (…last4)" status. Empty submit keeps the previously-saved value.
- Do not depend on the stdlib `cgi` module (removed in Python 3.13). All
  multipart parsing is done by a local helper using plain byte splitting.
- `uploads/` is gitignored and excluded from `app.collect_input_files`.
- File download only serves files under `outputs/`. Path traversal is
  rejected before any filesystem access.
"""

from __future__ import annotations

import argparse
import html
import json
import mimetypes
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import collect_input_files, run_pipeline

ENV_PATH = Path(".env")
OUTPUT_WHITELIST_ROOT = (ROOT / "outputs").resolve()

# Settings page only exposes the unified "KNOWLEDGEHARNESS_*" keys.
# Per-module overrides (TOPIC_/WEB_ENRICHMENT_) can still be edited in
# the .env file manually; they are not in the UI on purpose to keep the
# settings surface small.
API_ENV_KEYS = [
    "KNOWLEDGEHARNESS_API_URL",
    "KNOWLEDGEHARNESS_API_KEY",
]
SHOW_LAB_LINK = os.getenv("KH_UI_SHOW_LAB_LINK", "0").strip() == "1"

# ---------------------------------------------------------------------------
# Per-run upload limits
# ---------------------------------------------------------------------------
# These are defensive caps. The pipeline itself has no fixed upper bound,
# but OCR on large image batches is slow and the in-memory multipart
# parser scales with request size. These numbers are deliberately generous
# for typical study material but refuse "accidentally run on 200 files".

MAX_IMAGE_COUNT_PER_RUN = 10          # png/jpg/jpeg combined
MAX_TOTAL_FILES_PER_RUN = 20          # overall cap across all extensions
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024   # 20 MB per single uploaded file
MAX_REQUEST_BODY_BYTES = 200 * 1024 * 1024  # 200 MB per whole POST body

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}


def _parse_multipart(
    body: bytes,
    boundary: bytes,
) -> Tuple[Dict[str, List[str]], List[Tuple[str, str, bytes]]]:
    """Parse a multipart/form-data body without the deprecated `cgi` module.

    Returns:
        (fields, files) where
          fields = {name: [utf-8 decoded text value, ...]}
          files  = [(field_name, filename, raw_bytes), ...]
    """
    fields: Dict[str, List[str]] = {}
    files: List[Tuple[str, str, bytes]] = []
    if not boundary:
        return fields, files

    delim = b"--" + boundary
    for part in body.split(delim):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            # Skip the leading empty segment and the terminating "--".
            continue
        hdr_end = part.find(b"\r\n\r\n")
        if hdr_end < 0:
            continue
        hdr_blob = part[:hdr_end]
        payload = part[hdr_end + 4 :]

        disposition: Dict[str, str] = {}
        for line in hdr_blob.decode("utf-8", "replace").splitlines():
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            if k.strip().lower() != "content-disposition":
                continue
            for kv in v.split(";"):
                kv = kv.strip()
                if "=" in kv:
                    dk, dv = kv.split("=", 1)
                    disposition[dk.strip().lower()] = dv.strip().strip('"')

        name = disposition.get("name")
        if not name:
            continue
        filename = disposition.get("filename")
        if filename is None:
            fields.setdefault(name, []).append(
                payload.decode("utf-8", "replace")
            )
        elif filename:  # ignore empty-filename file fields (no file picked)
            files.append((name, filename, payload))

    return fields, files


def _load_local_env(path: str = ".env") -> None:
    env_file = Path(path)
    if not env_file.exists() or not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, val = s.split("=", 1)
        key = key.strip()
        val = val.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = val


def _read_env_pairs(path: Path = ENV_PATH) -> Dict[str, str]:
    pairs: Dict[str, str] = {}
    if not path.exists() or not path.is_file():
        return pairs
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, val = s.split("=", 1)
        pairs[key.strip()] = val.strip().strip("'\"")
    return pairs


def _write_env_pairs(updates: Dict[str, str], path: Path = ENV_PATH) -> List[str]:
    """Persist non-empty updates to .env without clobbering other keys.

    Empty submissions are treated as "keep previous value" so the UI can
    render blank inputs without resetting existing secrets when the user
    only wants to edit one field.

    Returns the list of keys that were actually updated.
    """
    existing_lines: List[str] = []
    if path.exists() and path.is_file():
        existing_lines = path.read_text(encoding="utf-8").splitlines()

    # Discard empty-string updates so leaving a field blank preserves the
    # existing value. Callers wanting to CLEAR a key must write a literal
    # sentinel, which this UI intentionally does not offer.
    effective = {k: v for k, v in updates.items() if v}
    if not effective:
        return []

    touched = set()
    new_lines: List[str] = []
    for raw in existing_lines:
        s = raw.strip()
        if not s or s.startswith("#") or "=" not in raw:
            new_lines.append(raw)
            continue
        key = raw.split("=", 1)[0].strip()
        if key in effective:
            new_lines.append(f"{key}={effective[key]}")
            touched.add(key)
        else:
            new_lines.append(raw)

    for k, v in effective.items():
        if k not in touched:
            new_lines.append(f"{k}={v}")

    if not new_lines:
        new_lines = [f"{k}={v}" for k, v in effective.items()]
    path.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")

    for k, v in effective.items():
        os.environ[k] = v

    return list(effective.keys())


def _mask_value(value: str) -> str:
    """Render a masked status string for an API credential.

    Never returns the underlying value; used only for UI indicator text.
    """
    v = (value or "").strip()
    if not v:
        return "未配置"
    if len(v) <= 4:
        return "已配置"
    return f"已配置（末 4 位：···{v[-4:]}）"


def _safe_filename(name: str) -> str:
    base = Path(name or "upload.bin").name.strip()
    if not base:
        base = "upload.bin"
    return base.replace("/", "_").replace("\\", "_")


# ---------------------------------------------------------------------------
# Uploaded file pool
# ---------------------------------------------------------------------------

UPLOAD_POOL_DIR = Path("uploads") / "ui_uploads"


def _list_uploaded_pool() -> List[Tuple[str, int, float]]:
    """List the upload pool as `(filename, size_bytes, mtime_epoch)`, newest first."""
    if not UPLOAD_POOL_DIR.exists():
        return []
    items: List[Tuple[str, int, float]] = []
    for p in UPLOAD_POOL_DIR.iterdir():
        if not p.is_file():
            continue
        try:
            stat = p.stat()
        except OSError:
            continue
        items.append((p.name, int(stat.st_size), float(stat.st_mtime)))
    items.sort(key=lambda t: t[2], reverse=True)
    return items


def _validate_pool_file(name: str) -> Path | None:
    """Return the resolved file Path if `name` safely resolves inside the
    upload pool, else None.

    Accepts any filename characters (including CJK, parentheses) as long as
    the resulting path, after resolution, stays inside UPLOAD_POOL_DIR.
    Rejects path separators, null bytes, leading dots, and absolute paths.
    """
    if not name or "\x00" in name:
        return None
    if "/" in name or "\\" in name or name.startswith("."):
        return None
    try:
        pool = UPLOAD_POOL_DIR.resolve()
    except OSError:
        return None
    try:
        target = (pool / name).resolve()
        target.relative_to(pool)
    except (ValueError, OSError):
        return None
    if not target.is_file():
        return None
    return target


def _clear_upload_pool() -> int:
    """Delete every file directly in the upload pool. Returns the count removed."""
    if not UPLOAD_POOL_DIR.exists():
        return 0
    removed = 0
    for p in UPLOAD_POOL_DIR.iterdir():
        if p.is_file():
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def _format_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.2f} MB"


def _resolve_output_dir(raw: str) -> Path:
    """Resolve a user-supplied output directory string.

    Rules (predictable for testing):
    - Empty input → `<ROOT>/outputs` (MVP default).
    - Absolute path → used as-is.
    - Relative path → resolved against the project root, NOT against the
      shell CWD where the UI happened to be launched. This matches the
      "以项目文件所在为基准" expectation.
    """
    raw = (raw or "").strip() or "outputs"
    p = Path(raw)
    if p.is_absolute():
        return p
    return (ROOT / raw).resolve()


def _download_support_hint(raw: str) -> str:
    """Explain in-line whether the browser-download link will work.

    UI's `/download` endpoint only serves files directly inside
    `<ROOT>/outputs`. Any deeper subdir or any directory outside that
    whitelist will still run the pipeline (and write files), but those
    files will only be accessible via the filesystem path shown above.
    """
    resolved = _resolve_output_dir(raw)
    try:
        rel = resolved.relative_to(OUTPUT_WHITELIST_ROOT)
    except ValueError:
        return (
            '<br/><span class="warn-text">此目录不在 <code>outputs/</code> 之下——'
            "运行仍会成功，但浏览器下载链接不可用（需手动打开路径）。</span>"
        )
    # Under OUTPUT_WHITELIST_ROOT. Only the root itself supports basename
    # downloads right now; deeper subdirs would require path support in
    # /download which is intentionally not there.
    if str(rel) in ("", "."):
        return ""
    return (
        '<br/><span class="warn-text">当前输出是 <code>outputs/</code> 的子目录，'
        "浏览器下载链接仅对 <code>outputs/</code> 根目录生效。</span>"
    )


def _store_uploaded_files(
    items: List[Tuple[str, str, bytes]],
) -> Tuple[List[str], List[str]]:
    """Persist uploaded file parts to `uploads/ui_uploads/` and return paths.

    Args:
        items: (field_name, original_filename, raw_bytes) triples from the
            multipart parser. Parts whose field_name is not `upload_files`
            are ignored.

    Empty payloads are skipped so the user re-submitting the form without
    picking a new file does not create a zero-byte placeholder. Payloads
    whose size exceeds ``MAX_FILE_SIZE_BYTES`` are also rejected.

    Returns:
        (saved_paths, rejected_descriptions) where each rejected_description
        is a short human-readable string ("filename (size): 超过单文件上限").
    """
    saved: List[str] = []
    rejected: List[str] = []
    if not items:
        return saved, rejected
    UPLOAD_POOL_DIR.mkdir(parents=True, exist_ok=True)

    for field_name, filename, data in items:
        if field_name != "upload_files":
            continue
        if not data:
            continue
        if len(data) > MAX_FILE_SIZE_BYTES:
            rejected.append(
                f"{filename}（{_format_size(len(data))}）: 超过单文件上限 "
                f"{_format_size(MAX_FILE_SIZE_BYTES)}"
            )
            continue
        base = _safe_filename(filename)
        target = UPLOAD_POOL_DIR / base
        stem = target.stem
        suffix = target.suffix
        idx = 1
        while target.exists():
            target = UPLOAD_POOL_DIR / f"{stem}_{idx}{suffix}"
            idx += 1
        target.write_bytes(data)
        saved.append(str(target))
    return saved, rejected


def _checked(v: bool) -> str:
    return "checked" if v else ""


def _selected(value: str, target: str) -> str:
    return "selected" if value == target else ""


def _relative_to_outputs(abs_path: str) -> str:
    """If `abs_path` lives inside `outputs/`, return its basename (for the
    `/download?name=<basename>` endpoint). Otherwise return empty string.
    """
    if not abs_path:
        return ""
    try:
        p = Path(abs_path).resolve()
        p.relative_to(OUTPUT_WHITELIST_ROOT)
    except Exception:
        return ""
    return p.name


def _render_download_link(label: str, abs_path: str) -> str:
    """Lab-mode-style download row with full path + hint (keeps existing
    verbose behaviour for diagnostics)."""
    if not abs_path:
        return f"<p><strong>{html.escape(label)}:</strong> （未生成）</p>"
    basename = _relative_to_outputs(abs_path)
    escaped_path = html.escape(abs_path)
    if basename:
        return (
            f'<p><strong>{html.escape(label)}:</strong> '
            f'<a href="/download?name={html.escape(basename)}" download>{html.escape(basename)}</a> '
            f'<span class="hint">({escaped_path})</span></p>'
        )
    return (
        f'<p><strong>{html.escape(label)}:</strong> {escaped_path} '
        f'<span class="hint">(不在 outputs/ 下，无法通过浏览器下载，请手动打开路径)</span></p>'
    )


def _render_download_button(label: str, ext_text: str, abs_path: str) -> str:
    """Prod-mode-style download chip. Single button per file, compact."""
    if not abs_path:
        return (
            f'<span class="download-missing">{html.escape(label)} '
            f'<span class="ext">{html.escape(ext_text)}</span>（未生成）</span>'
        )
    basename = _relative_to_outputs(abs_path)
    if not basename:
        return (
            f'<span class="download-missing" title="{html.escape(abs_path)}">'
            f'{html.escape(label)} <span class="ext">{html.escape(ext_text)}</span>'
            f'（路径不在 outputs/ 下）</span>'
        )
    return (
        f'<a class="download-btn" href="/download?name={html.escape(basename)}" download '
        f'title="{html.escape(abs_path)}">'
        f'{html.escape(label)} <span class="ext">{html.escape(ext_text)}</span>'
        f'</a>'
    )


def _render_result_summary(result: Dict[str, Any]) -> str:
    """Compact stats card above the raw markdown — a real summary, not a pre dump."""
    validation = result.get("validation", {}) or {}
    warnings = validation.get("warnings", []) or []
    overview = result.get("overview", {}) or {}
    ingestion = overview.get("ingestion_summary", {}) or {}
    topic_output = result.get("topic_classification", {}) or {}
    topic_stats = topic_output.get("stats", {}) or {}
    topic_items = topic_output.get("items", []) or []
    categorized = result.get("categorized_notes", {}) or {}

    is_valid_badge_class = "badge-ok" if validation.get("is_valid") else "badge-warn"
    is_valid_text = "通过" if validation.get("is_valid") else "有告警"

    topic_rows = "".join(
        f"<tr><td>{html.escape(str(it.get('source_name') or ''))}</td>"
        f"<td>{html.escape(str(it.get('topic_label') or ''))}</td>"
        f"<td>{html.escape(str(it.get('confidence') or ''))}</td>"
        f"<td>{html.escape('API' if it.get('used_api') else 'local')}</td></tr>"
        for it in topic_items[:20]
    )
    cat_counts = "".join(
        f"<li>{html.escape(cat)}: <strong>{len(items or [])}</strong></li>"
        for cat, items in categorized.items()
    )
    warnings_html = "".join(f"<li>{html.escape(str(w))}</li>" for w in warnings) or "<li>（无）</li>"

    return f"""
    <section class="card summary">
      <h2>处理摘要</h2>
      <div class="summary-grid">
        <div>
          <h3>校验状态</h3>
          <p><span class="badge {is_valid_badge_class}">{is_valid_text}</span></p>
          <ul>{warnings_html}</ul>
        </div>
        <div>
          <h3>输入统计</h3>
          <ul>
            <li>检测: <strong>{ingestion.get('detected', 0)}</strong></li>
            <li>成功: <strong>{ingestion.get('succeeded', 0)}</strong></li>
            <li>失败: <strong>{ingestion.get('failed', 0)}</strong></li>
            <li>空抽取: <strong>{ingestion.get('empty_extracted', 0)}</strong></li>
            <li>OCR 后端: <strong>{html.escape(str(ingestion.get('ocr_backend', 'unavailable')))}</strong></li>
            <li>chunk 数: <strong>{overview.get('chunk_count', 0)}</strong></li>
          </ul>
        </div>
        <div>
          <h3>内容功能分类</h3>
          <ul>{cat_counts or '<li>（无）</li>'}</ul>
        </div>
        <div>
          <h3>主题粗分类</h3>
          <p class="hint">API 协助: <strong>{topic_stats.get('used_api_count', 0)}</strong> · 降级: <strong>{topic_stats.get('degraded_count', 0)}</strong></p>
          <table class="mini">
            <thead><tr><th>文件</th><th>主题</th><th>置信度</th><th>来源</th></tr></thead>
            <tbody>{topic_rows or '<tr><td colspan=4>（无）</td></tr>'}</tbody>
          </table>
        </div>
      </div>
    </section>
    """


def _render_page(
    *,
    form: Dict[str, Any],
    error: str = "",
    result: Dict[str, Any] | None = None,
    uploaded_files: List[str] | None = None,
    pool_selected: set[str] | None = None,
    flash: str = "",
    lab_mode: bool = False,
) -> str:
    output_dir = str(form.get("output_dir", "outputs"))
    topic_mode = str(form.get("topic_mode", "auto"))
    enable_web = bool(form.get("enable_web_enrichment", False))
    web_mode = str(form.get("web_enrichment_mode", "auto"))
    kp_min = str(form.get("keypoint_min_confidence", "0.0"))
    kp_max = str(form.get("keypoint_max_points", "12"))
    export_docx = bool(form.get("export_docx", False))
    uploaded_files = uploaded_files or []
    pool_selected = pool_selected or set()

    result_html = ""
    if result is not None:
        export_paths = result.get("export_paths", {}) or {}
        md_path = str(export_paths.get("md_path", "")).strip()
        json_path = str(export_paths.get("json_path", "")).strip()
        docx_path = str(export_paths.get("docx_path", "")).strip()

        final_doc_preview = ""
        if md_path:
            p = Path(md_path)
            if p.exists() and p.is_file():
                text = p.read_text(encoding="utf-8", errors="replace")
                final_doc_preview = text[:12000]
                if len(text) > 12000:
                    final_doc_preview += "\n\n…（已截断，请用上方下载链接获取完整文件）"
            else:
                final_doc_preview = "未找到最终文档文件，请先确认本次运行已成功导出。"
        else:
            final_doc_preview = "本次运行未返回最终文档路径。"

        if lab_mode:
            download_html = (
                _render_download_link("Markdown", md_path)
                + _render_download_link("JSON", json_path)
                + _render_download_link("Word (.docx)", docx_path)
            )
            result_html = f"""
            {_render_result_summary(result)}
            <section class="card">
              <h2>最终文档下载</h2>
              {download_html}
            </section>
            <section class="card">
              <h2>最终文档预览（Markdown 源文本）</h2>
              <pre>{html.escape(final_doc_preview)}</pre>
            </section>
            """
        else:
            download_chips = (
                _render_download_button("下载笔记", "md", md_path)
                + _render_download_button("下载 Word", "docx", docx_path)
            )
            result_html = f"""
            <section class="card">
              <h2>笔记已生成</h2>
              <div class="download-row">{download_chips}</div>
            </section>
            <section class="card">
              <h2>笔记预览</h2>
              <pre>{html.escape(final_doc_preview)}</pre>
            </section>
            """

    error_html = (
        f'<div class="error">{html.escape(error)}</div>'
        if error
        else ""
    )
    flash_html = (
        f'<div class="ok">{html.escape(flash)}</div>'
        if flash
        else ""
    )

    # --- Pool card ---
    pool_items = _list_uploaded_pool()
    pool_rows_html: List[str] = []
    # Per-extension counters. Group png/jpg/jpeg as they share OCR semantics
    # and are jointly capped by MAX_IMAGE_COUNT_PER_RUN.
    from collections import Counter
    import time as _time
    ext_counter: Counter = Counter()
    for name, _, _ in pool_items:
        ext = Path(name).suffix.lower().lstrip(".") or "(无后缀)"
        ext_counter[ext] += 1

    # Build the breakdown line, count-descending then ext-ascending.
    breakdown_parts: List[str] = []
    image_total = ext_counter["png"] + ext_counter["jpg"] + ext_counter["jpeg"]
    for ext, count in sorted(ext_counter.items(), key=lambda kv: (-kv[1], kv[0])):
        breakdown_parts.append(f".{ext} × {count}")
    breakdown_line = " · ".join(breakdown_parts)

    for name, size, mtime in pool_items:
        date_str = _time.strftime("%Y-%m-%d %H:%M", _time.localtime(mtime))
        ext = Path(name).suffix.lower().lstrip(".") or "(无后缀)"
        is_image = ext in {"png", "jpg", "jpeg"}
        pill_class = "type-pill type-img" if is_image else "type-pill"
        escaped = html.escape(name)
        checked = "checked" if name in pool_selected else ""
        pool_rows_html.append(
            "<li class=\"pool-row\">"
            "<label class=\"pool-pick\">"
            f'<input type="checkbox" name="existing_files" value="{escaped}" {checked} form="runForm" />'
            f'<span class="{pill_class}">{html.escape(ext)}</span>'
            f'<span class="pool-name">{escaped}</span>'
            f'<span class="pool-meta">{_format_size(size)} · {date_str}</span>'
            "</label>"
            '<form method="post" action="/uploads/remove" class="pool-remove">'
            f'<input type="hidden" name="name" value="{escaped}" />'
            f'<input type="hidden" name="ui_mode" value="{"lab" if lab_mode else "prod"}" />'
            '<button type="submit" class="link-btn" title="从文件池移除">删除</button>'
            "</form>"
            "</li>"
        )

    if pool_items:
        image_warn = ""
        if image_total > MAX_IMAGE_COUNT_PER_RUN:
            image_warn = (
                f'<span class="pool-warn">当前池中有 {image_total} 张图片，超过单次处理上限 '
                f'{MAX_IMAGE_COUNT_PER_RUN} 张——请勾选时只选其中部分</span>'
            )
        total_warn = ""
        if len(pool_items) > MAX_TOTAL_FILES_PER_RUN:
            total_warn = (
                f'<span class="pool-warn">池中文件总数 {len(pool_items)} 已超过单次处理上限 '
                f'{MAX_TOTAL_FILES_PER_RUN} 个</span>'
            )
        pool_card_html = f"""
        <section class="card">
          <div class="pool-head">
            <h2>历史上传 <span class="pool-count">{len(pool_items)} 个</span></h2>
            <form method="post" action="/uploads/clear" class="pool-clear">
              <input type="hidden" name="ui_mode" value="{"lab" if lab_mode else "prod"}" />
              <button type="submit" class="danger-btn">清空全部</button>
            </form>
          </div>
          <p class="pool-breakdown">{html.escape(breakdown_line)}</p>
          {image_warn}{total_warn}
          <ul class="pool-list">{''.join(pool_rows_html)}</ul>
        </section>
        """
    else:
        pool_card_html = ""

    mode_badge = (
        '<span class="mode-badge" title="带完整诊断信息">调试视图</span>'
        if lab_mode
        else ''
    )
    page_title = "KnowledgeHarness"
    page_subtitle = (
        "调试视图：带完整分类、校验、原始 JSON 等诊断信息。"
        if lab_mode
        else "上传学习资料，自动整理为结构化复习笔记。"
    )
    run_status_text = (
        "流水线执行中：解析 → 切分 → 主题粗分类 → 内容分类 → 总结 → 重点 → 补充 → 校验 → 导出…"
        if lab_mode
        else "正在处理资料并生成笔记，请稍候…"
    )
    submit_button_label = "运行流水线" if lab_mode else "生成笔记"

    prod_controls_html = """
          <div class="row">
            <label><input type="checkbox" name="export_docx" {docx_checked} /> 同时导出 Word（.docx）</label>
          </div>
          <input type="hidden" name="topic_mode" value="auto" />
          <input type="hidden" name="web_enrichment_mode" value="auto" />
          <input type="hidden" name="keypoint_min_confidence" value="0.0" />
          <input type="hidden" name="keypoint_max_points" value="12" />
    """.format(docx_checked=_checked(export_docx))

    lab_controls_html = f"""
          <div class="row">
            <label><input type="checkbox" name="enable_web_enrichment" {_checked(enable_web)} /> 启用 Web 补充</label>
            <label><input type="checkbox" name="export_docx" {_checked(export_docx)} /> 同时导出 Word（.docx）</label>
          </div>
          <details>
            <summary>高级选项</summary>
            <div class="grid">
              <div class="row">
                <label for="topic_mode">主题分类模式</label>
                <select id="topic_mode" name="topic_mode">
                  <option value="auto" {_selected(topic_mode, "auto")}>自动（auto）</option>
                  <option value="local" {_selected(topic_mode, "local")}>本地（local）</option>
                  <option value="api" {_selected(topic_mode, "api")}>接口（api）</option>
                </select>
              </div>
              <div class="row">
                <label for="web_enrichment_mode">Web 补充模式</label>
                <select id="web_enrichment_mode" name="web_enrichment_mode">
                  <option value="auto" {_selected(web_mode, "auto")}>自动（auto）</option>
                  <option value="off" {_selected(web_mode, "off")}>关闭（off）</option>
                  <option value="local" {_selected(web_mode, "local")}>本地（local）</option>
                  <option value="api" {_selected(web_mode, "api")}>接口（api）</option>
                </select>
              </div>
              <div class="row">
                <label for="keypoint_min_confidence">关键点最小置信度（0–1）</label>
                <input id="keypoint_min_confidence" type="number" step="0.05" min="0" max="1" name="keypoint_min_confidence" value="{html.escape(kp_min)}" />
              </div>
              <div class="row">
                <label for="keypoint_max_points">关键点最大数量</label>
                <input id="keypoint_max_points" type="number" step="1" min="1" max="200" name="keypoint_max_points" value="{html.escape(kp_max)}" />
              </div>
            </div>
          </details>
    """

    controls_html = lab_controls_html if lab_mode else prod_controls_html
    if lab_mode:
        lab_switch_html = '<a class="button-link ghost-link" href="/">切换为对外视图</a>'
    elif SHOW_LAB_LINK:
        lab_switch_html = '<a class="button-link ghost-link" href="/lab">进入调试视图</a>'
    else:
        lab_switch_html = ""

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>KnowledgeHarness · 笔记整理</title>
  <style>
    /* ---- design tokens ----
     * Single neutral palette + one accent color. No competing greens and blues.
     * Inspired by common Linear / Vercel dashboards rather than "early bootstrap".
     */
    :root {{
      --bg:           #f6f7f9;
      --surface:      #ffffff;
      --surface-2:    #f9fafb;
      --border:       #e5e7eb;
      --border-soft:  #eef0f3;
      --text:         #111827;
      --text-muted:   #6b7280;
      --accent:       #111827;   /* primary button = near-black for a calm, pro feel */
      --accent-ink:   #ffffff;
      --accent-soft:  #f3f4f6;
      --danger:       #b91c1c;
      --ok:           #047857;
      --warn:         #b45309;
      --radius:       10px;
      --radius-sm:    6px;
      --shadow-1:     0 1px 2px rgba(16, 24, 40, 0.04), 0 1px 3px rgba(16, 24, 40, 0.06);
    }}

    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; padding: 0; }}
    body {{
      padding: 32px 24px 64px;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                   "Helvetica Neue", Helvetica, Arial,
                   "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei",
                   "Noto Sans CJK SC", sans-serif;
      font-size: 14.5px;
      line-height: 1.55;
      -webkit-font-smoothing: antialiased;
    }}
    .wrap {{ max-width: 880px; margin: 0 auto; }}

    /* header */
    .app-header {{ margin-bottom: 20px; }}
    .app-header h1 {{
      margin: 0;
      font-size: 22px;
      font-weight: 600;
      letter-spacing: -0.01em;
      display: flex; align-items: center; gap: 10px;
    }}
    .app-header .subtitle {{
      margin: 6px 0 0 0;
      color: var(--text-muted);
      font-size: 13.5px;
    }}

    /* cards */
    .card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 20px 22px;
      margin-bottom: 16px;
      box-shadow: var(--shadow-1);
    }}
    .card h2 {{
      margin: 0 0 14px 0;
      font-size: 15px;
      font-weight: 600;
      letter-spacing: -0.005em;
    }}
    .card h3 {{
      margin: 0 0 8px 0; font-size: 13px; font-weight: 600;
      color: var(--text-muted); text-transform: none;
    }}

    /* typography helpers */
    label {{ display: block; margin-bottom: 6px; font-weight: 500; font-size: 13.5px; }}
    .hint {{ color: var(--text-muted); font-size: 12.5px; margin: 6px 0 0 0; }}
    code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12.5px; background: var(--accent-soft);
      padding: 1px 5px; border-radius: 4px;
    }}

    /* form controls */
    input[type=text], input[type=number], input[type=password], textarea, select {{
      width: 100%; padding: 8px 10px;
      border: 1px solid var(--border); border-radius: var(--radius-sm);
      background: var(--surface); color: var(--text);
      font: inherit;
      transition: border-color .15s, box-shadow .15s;
    }}
    input:focus, textarea:focus, select:focus {{
      outline: none;
      border-color: var(--text);
      box-shadow: 0 0 0 3px rgba(17, 24, 39, 0.08);
    }}
    .row {{ margin-bottom: 14px; }}

    /* buttons */
    button, .button-link {{
      display: inline-block; text-decoration: none; font: inherit;
      font-weight: 500; cursor: pointer;
      padding: 8px 16px; border-radius: var(--radius-sm);
      border: 1px solid transparent;
      transition: background .15s, border-color .15s, color .15s;
    }}
    button {{
      background: var(--accent); color: var(--accent-ink);
    }}
    button:hover {{ background: #000; }}
    button[disabled] {{ background: #9ca3af; cursor: progress; }}
    .button-link {{
      background: var(--surface); color: var(--text);
      border-color: var(--border);
      margin-left: 8px;
    }}
    .button-link:hover {{ background: var(--accent-soft); }}
    .ghost-link {{ background: transparent; color: var(--text-muted); border-color: var(--border-soft); }}
    .link-btn {{
      background: transparent; color: var(--danger);
      border: 0; padding: 2px 6px; font-size: 12.5px;
      cursor: pointer; text-decoration: underline;
    }}
    .danger-btn {{
      background: var(--surface); color: var(--danger);
      border: 1px solid #fecaca;
      padding: 6px 10px; font-size: 12.5px; font-weight: 500; border-radius: var(--radius-sm);
    }}
    .danger-btn:hover {{ background: #fef2f2; }}

    /* inline banners */
    .error {{ background: #fef2f2; color: #991b1b; border: 1px solid #fecaca;
             padding: 10px 12px; border-radius: var(--radius-sm); margin-bottom: 12px;
             font-size: 13.5px; }}
    .ok {{ background: #ecfdf5; color: var(--ok); border: 1px solid #a7f3d0;
          padding: 10px 12px; border-radius: var(--radius-sm); margin-bottom: 12px;
          font-size: 13.5px; }}
    .status {{ background: #fff7ed; color: var(--warn); border: 1px solid #fde68a;
              padding: 10px 12px; border-radius: var(--radius-sm); margin-bottom: 12px;
              font-size: 13.5px; }}

    /* preview <pre> */
    pre {{
      white-space: pre-wrap; word-break: break-word;
      background: var(--surface-2); border: 1px solid var(--border-soft);
      border-radius: var(--radius-sm); padding: 12px 14px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12.5px; line-height: 1.55;
      max-height: 420px; overflow-y: auto; margin: 0;
    }}

    /* mode badge — shown ONLY in lab mode */
    .mode-badge {{
      display: inline-flex; align-items: center;
      padding: 2px 8px; border-radius: 999px;
      background: #fef3c7; color: var(--warn); border: 1px solid #fde68a;
      font-size: 11.5px; font-weight: 500;
    }}

    /* validation badge used inside lab summary */
    .badge {{ display: inline-block; padding: 2px 10px; border-radius: 999px;
             font-weight: 500; font-size: 12px; }}
    .badge-ok {{ background: #ecfdf5; color: var(--ok); border: 1px solid #a7f3d0; }}
    .badge-warn {{ background: #fef3c7; color: var(--warn); border: 1px solid #fde68a; }}

    /* grids (lab summary) */
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    .grid-single {{ display: grid; grid-template-columns: 1fr; gap: 12px; }}
    .summary .summary-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
    .summary-grid > div {{
      background: var(--surface-2); border: 1px solid var(--border-soft);
      border-radius: var(--radius-sm); padding: 12px;
    }}
    .summary-grid ul {{ padding-left: 18px; margin: 6px 0; }}
    .summary-grid li {{ font-size: 13px; color: var(--text); }}
    table.mini {{ width: 100%; border-collapse: collapse; font-size: 12.5px; }}
    table.mini th {{ font-weight: 500; color: var(--text-muted); }}
    table.mini th, table.mini td {{ border-bottom: 1px solid var(--border-soft); padding: 5px 6px; text-align: left; }}

    /* details / advanced options */
    details {{
      border: 1px solid var(--border); border-radius: var(--radius-sm);
      padding: 10px 14px; background: var(--surface-2); margin-top: 6px;
    }}
    details > summary {{
      cursor: pointer; font-weight: 500; font-size: 13.5px;
      margin-bottom: 6px; list-style: none;
    }}
    details > summary::before {{
      content: "▸"; display: inline-block; margin-right: 6px;
      color: var(--text-muted); transition: transform .15s;
    }}
    details[open] > summary::before {{ transform: rotate(90deg); }}

    /* ---- upload pool ---- */
    .pool-head {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; }}
    .pool-head h2 {{ margin: 0; display: flex; align-items: center; gap: 10px; }}
    .pool-count {{
      display: inline-block; padding: 2px 10px;
      background: var(--accent-soft); color: var(--text); border: 1px solid var(--border);
      border-radius: 999px; font-size: 12px; font-weight: 500;
    }}
    .pool-breakdown {{
      margin: 8px 0 4px 0; color: var(--text-muted); font-size: 12.5px;
    }}
    .pool-warn {{
      display: block; margin: 6px 0; padding: 8px 10px;
      background: #fff7ed; color: var(--warn); border: 1px solid #fde68a;
      border-radius: var(--radius-sm); font-size: 12.5px;
    }}
    .pool-list {{ list-style: none; padding: 0; margin: 10px 0 0 0; }}
    .pool-row {{
      display: flex; align-items: center; justify-content: space-between;
      padding: 8px 4px; border-bottom: 1px solid var(--border-soft);
    }}
    .pool-row:last-child {{ border-bottom: 0; }}
    .pool-pick {{
      display: flex; align-items: center; gap: 10px; margin: 0;
      font-weight: 400; font-size: 13.5px;
      flex: 1 1 auto; cursor: pointer; min-width: 0;
    }}
    .pool-pick input[type=checkbox] {{ margin: 0; }}
    .pool-name {{ font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .pool-meta {{ color: var(--text-muted); font-size: 12px; flex-shrink: 0; }}
    .pool-remove {{ margin: 0; flex-shrink: 0; }}
    .type-pill {{
      display: inline-block; min-width: 40px; text-align: center;
      padding: 2px 8px; border-radius: 4px;
      background: var(--accent-soft); color: var(--text); border: 1px solid var(--border);
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 11px; font-weight: 500; text-transform: lowercase;
      flex-shrink: 0;
    }}
    .type-pill.type-img {{
      background: #fef3c7; color: var(--warn); border-color: #fde68a;
    }}
    .warn-text {{ color: var(--warn); font-size: 12.5px; }}

    /* ---- download buttons (prod mode) ---- */
    .download-row {{
      display: flex; flex-wrap: wrap; gap: 8px;
      margin-top: 4px;
    }}
    .download-btn {{
      display: inline-flex; align-items: center; gap: 8px;
      padding: 8px 14px; font-weight: 500;
      border: 1px solid var(--border); border-radius: var(--radius-sm);
      background: var(--surface); color: var(--text);
      text-decoration: none; font-size: 13.5px;
    }}
    .download-btn:hover {{ background: var(--accent-soft); }}
    .download-btn .ext {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 11px; color: var(--text-muted);
      padding: 1px 6px; border-radius: 4px; background: var(--accent-soft);
    }}
    .download-missing {{
      display: inline-flex; align-items: center;
      padding: 8px 14px; font-size: 13.5px; color: var(--text-muted);
      border: 1px dashed var(--border); border-radius: var(--radius-sm);
    }}

    /* ---- responsive ---- */
    @media (max-width: 720px) {{
      body {{ padding: 20px 14px 48px; font-size: 14px; }}
      .card {{ padding: 16px; }}
      .grid, .summary .summary-grid {{ grid-template-columns: 1fr; }}
      .pool-meta {{ display: none; }}
    }}
  </style>
  <script>
    document.addEventListener("DOMContentLoaded", function () {{
      var form = document.querySelector("form[action='/run']");
      if (!form) return;
      form.addEventListener("submit", function () {{
        var btn = form.querySelector("button[type=submit]");
        if (btn) {{
          btn.disabled = true;
          btn.textContent = "处理中，请稍候…";
        }}
        var wrap = document.querySelector(".wrap");
        if (wrap) {{
          var status = document.createElement("div");
          status.className = "status";
          status.textContent = "{html.escape(run_status_text)}";
          wrap.insertBefore(status, wrap.firstChild);
        }}
      }});
    }});
  </script>
</head>
<body>
  <div class="wrap">
    <header class="app-header">
      <h1>{page_title}{mode_badge}</h1>
      <p class="subtitle">{html.escape(page_subtitle)}</p>
    </header>

    <section class="card">
      {flash_html}
      {error_html}
      <form id="runForm" method="post" action="/run" enctype="multipart/form-data">
        <input type="hidden" name="ui_mode" value="{ 'lab' if lab_mode else 'prod' }" />
        <div class="row">
          <label for="upload_files">上传资料</label>
          <input id="upload_files" type="file" name="upload_files" multiple />
          <p class="hint">
            支持 txt / md / pdf / docx，以及可选 OCR 图片 png / jpg / jpeg。
            上限：{MAX_TOTAL_FILES_PER_RUN} 个文件 · 图片 ≤ {MAX_IMAGE_COUNT_PER_RUN} 张 · 单文件 ≤ {_format_size(MAX_FILE_SIZE_BYTES)}。
            上传后会保留在历史列表中，下次不用重传。
          </p>
        </div>

        <div class="grid-single">
          <div class="row">
            <label for="output_dir">输出目录</label>
            <input id="output_dir" type="text" name="output_dir" value="{html.escape(output_dir)}" />
            <p class="hint">
              相对路径基于项目根 <code>{html.escape(str(ROOT))}</code>；本次将写入
              <code>{html.escape(str(_resolve_output_dir(output_dir)))}</code>。
              {_download_support_hint(output_dir)}
            </p>
          </div>
        </div>

        {controls_html}
        <div class="row" style="margin-top: 18px; margin-bottom: 0;">
          <button type="submit">{submit_button_label}</button>
          <a class="button-link" href="/settings">API 设置</a>
          {lab_switch_html}
        </div>
      </form>
    </section>
    {pool_card_html}
    {result_html}
  </div>
</body>
</html>"""


def _render_settings_page(error: str = "", success: str = "") -> str:
    """Settings page that never echoes API values back into the DOM.

    Instead shows a masked status line (e.g. "已配置（末 4 位：···abcd）") and
    leaves the input empty. An empty submission keeps the existing value.
    """
    envs = _read_env_pairs()
    statuses: Dict[str, str] = {}
    for key in API_ENV_KEYS:
        current = envs.get(key) or os.getenv(key) or ""
        statuses[key] = _mask_value(current)

    error_html = f'<div class="error">{html.escape(error)}</div>' if error else ""
    success_html = f'<div class="ok">{html.escape(success)}</div>' if success else ""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>API 设置 · KnowledgeHarness</title>
  <style>
    :root {{
      --bg: #f6f7f9; --surface: #ffffff; --surface-2: #f9fafb;
      --border: #e5e7eb; --border-soft: #eef0f3;
      --text: #111827; --text-muted: #6b7280;
      --accent: #111827; --accent-ink: #ffffff; --accent-soft: #f3f4f6;
      --ok: #047857;
      --radius: 10px; --radius-sm: 6px;
      --shadow-1: 0 1px 2px rgba(16,24,40,.04), 0 1px 3px rgba(16,24,40,.06);
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; padding: 0; }}
    body {{
      padding: 32px 24px 64px; background: var(--bg); color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                   "Helvetica Neue", Helvetica, Arial,
                   "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei",
                   "Noto Sans CJK SC", sans-serif;
      font-size: 14.5px; line-height: 1.55;
      -webkit-font-smoothing: antialiased;
    }}
    .wrap {{ max-width: 640px; margin: 0 auto; }}
    .app-header h1 {{ margin: 0; font-size: 22px; font-weight: 600; letter-spacing: -0.01em; }}
    .app-header .subtitle {{ margin: 6px 0 0 0; color: var(--text-muted); font-size: 13.5px; }}
    .app-header {{ margin-bottom: 20px; }}
    .card {{
      background: var(--surface); border: 1px solid var(--border);
      border-radius: var(--radius); padding: 20px 22px; margin-bottom: 16px;
      box-shadow: var(--shadow-1);
    }}
    label {{ display: block; margin-bottom: 6px; font-weight: 500; font-size: 13.5px; }}
    input[type=text], input[type=password] {{
      width: 100%; padding: 8px 10px;
      border: 1px solid var(--border); border-radius: var(--radius-sm);
      background: var(--surface); font: inherit;
      transition: border-color .15s, box-shadow .15s;
    }}
    input:focus {{ outline: none; border-color: var(--text);
                  box-shadow: 0 0 0 3px rgba(17,24,39,.08); }}
    .row {{ margin-bottom: 18px; }}
    .status-chip {{
      display: inline-block; padding: 2px 10px; border-radius: 999px;
      background: var(--accent-soft); color: var(--text-muted);
      font-size: 12px; margin-bottom: 6px;
    }}
    button {{
      background: var(--accent); color: var(--accent-ink);
      border: 0; border-radius: var(--radius-sm);
      padding: 8px 16px; font: inherit; font-weight: 500; cursor: pointer;
    }}
    button:hover {{ background: #000; }}
    .back {{
      display: inline-block; margin-left: 8px; text-decoration: none;
      background: var(--surface); color: var(--text);
      border: 1px solid var(--border); border-radius: var(--radius-sm);
      padding: 8px 16px; font-weight: 500;
    }}
    .back:hover {{ background: var(--accent-soft); }}
    .hint {{ color: var(--text-muted); font-size: 12.5px; margin-top: 0; }}
    code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12.5px; background: var(--accent-soft);
      padding: 1px 5px; border-radius: 4px;
    }}
    .error {{ background: #fef2f2; color: #991b1b; border: 1px solid #fecaca;
             padding: 10px 12px; border-radius: var(--radius-sm); margin-bottom: 12px; font-size: 13.5px; }}
    .ok {{ background: #ecfdf5; color: var(--ok); border: 1px solid #a7f3d0;
          padding: 10px 12px; border-radius: var(--radius-sm); margin-bottom: 12px; font-size: 13.5px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <header class="app-header">
      <h1>API 设置</h1>
      <p class="subtitle">密钥写入项目根 <code>.env</code>。留空字段表示保持当前值。</p>
    </header>
    <section class="card">
      {error_html}
      {success_html}
      <form method="post" action="/settings" autocomplete="off">
        <div class="row">
          <label for="KNOWLEDGEHARNESS_API_URL">统一 API 地址</label>
          <span class="status-chip">{html.escape(statuses['KNOWLEDGEHARNESS_API_URL'])}</span>
          <input id="KNOWLEDGEHARNESS_API_URL" type="text"
                 name="KNOWLEDGEHARNESS_API_URL" value=""
                 placeholder="留空保持当前值" autocomplete="off" />
          <p class="hint">对应环境变量 <code>KNOWLEDGEHARNESS_API_URL</code>。</p>
        </div>

        <div class="row">
          <label for="KNOWLEDGEHARNESS_API_KEY">统一 API 密钥</label>
          <span class="status-chip">{html.escape(statuses['KNOWLEDGEHARNESS_API_KEY'])}</span>
          <input id="KNOWLEDGEHARNESS_API_KEY" type="password"
                 name="KNOWLEDGEHARNESS_API_KEY" value=""
                 placeholder="留空保持当前值" autocomplete="new-password" />
          <p class="hint">出于安全原因，当前值不会回填输入框；要清空请手动编辑 <code>.env</code>。按模块覆盖请参考 <code>.env.example</code>。</p>
        </div>

        <button type="submit">保存</button>
        <a class="back" href="/">返回</a>
      </form>
    </section>
  </div>
</body>
</html>"""


class _Handler(BaseHTTPRequestHandler):
    # Avoid BaseHTTPRequestHandler's default noisy access log for every
    # asset request -- keep `print()`-based startup log clean.
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _write_html(self, body: str, status: int = 200) -> None:
        raw = body.encode("utf-8", errors="replace")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _serve_download(self, query: str) -> None:
        """Serve a single file from the whitelisted outputs directory.

        Strict checks:
        - `name` must be a bare basename (no path separators, no leading dot)
        - resolved path must lie under OUTPUT_WHITELIST_ROOT
        """
        params = parse_qs(query, keep_blank_values=False)
        name = (params.get("name") or [""])[0].strip()
        if not name or "/" in name or "\\" in name or name.startswith("."):
            self._write_html("<h1>invalid file name</h1>", status=400)
            return
        if not re.match(r"^[\w.\-]+$", name):
            self._write_html("<h1>invalid file name</h1>", status=400)
            return

        try:
            target = (OUTPUT_WHITELIST_ROOT / name).resolve()
            target.relative_to(OUTPUT_WHITELIST_ROOT)
        except ValueError:
            self._write_html("<h1>path traversal blocked</h1>", status=400)
            return
        if not target.exists() or not target.is_file():
            self._write_html("<h1>not found</h1>", status=404)
            return

        mimetype, _ = mimetypes.guess_type(target.name)
        if not mimetype:
            if target.suffix.lower() == ".md":
                mimetype = "text/markdown; charset=utf-8"
            elif target.suffix.lower() == ".json":
                mimetype = "application/json; charset=utf-8"
            else:
                mimetype = "application/octet-stream"

        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="{target.name}"',
        )
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, location: str, status: int = 303) -> None:
        """Post-redirect-get: 303 makes the browser issue a GET on `location`."""
        self.send_response(status)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        route = parsed.path
        flash_params = parse_qs(parsed.query, keep_blank_values=True)
        flash = (flash_params.get("flash") or [""])[0][:200]
        if route == "/":
            self._write_html(_render_page(form={}, flash=flash, lab_mode=False))
            return
        if route == "/lab":
            self._write_html(_render_page(form={}, flash=flash, lab_mode=True))
            return
        if route == "/settings":
            self._write_html(_render_settings_page())
            return
        if route == "/download":
            self._serve_download(parsed.query)
            return
        self._write_html("<h1>未找到页面</h1>", status=404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/settings":
            length = int(self.headers.get("Content-Length", "0"))
            payload = self.rfile.read(length).decode("utf-8", errors="replace")
            form_raw = parse_qs(payload, keep_blank_values=True)
            try:
                updates = {
                    k: (form_raw.get(k) or [""])[0].strip()
                    for k in API_ENV_KEYS
                }
                touched = _write_env_pairs(updates)
                msg = (
                    f"保存成功：更新了 {', '.join(touched)}"
                    if touched
                    else "未更改任何字段（所有字段留空视为保持原值）"
                )
                self._write_html(_render_settings_page(success=msg))
            except Exception as exc:
                self._write_html(
                    _render_settings_page(error=f"保存失败: {exc}"),
                    status=400,
                )
            return

        if self.path == "/uploads/clear":
            length = int(self.headers.get("Content-Length", "0"))
            payload = self.rfile.read(length).decode("utf-8", errors="replace")
            form_raw = parse_qs(payload, keep_blank_values=True)
            mode = (form_raw.get("ui_mode") or ["prod"])[0]
            removed = _clear_upload_pool()
            # POST-redirect-GET so refresh doesn't re-submit.
            from urllib.parse import quote
            target = "/lab" if mode == "lab" else "/"
            self._redirect(f"{target}?flash={quote(f'已清空文件池，移除 {removed} 个文件')}")
            return

        if self.path == "/uploads/remove":
            length = int(self.headers.get("Content-Length", "0"))
            payload = self.rfile.read(length).decode("utf-8", errors="replace")
            form_raw = parse_qs(payload, keep_blank_values=True)
            name = (form_raw.get("name") or [""])[0].strip()
            mode = (form_raw.get("ui_mode") or ["prod"])[0]
            from urllib.parse import quote
            target = _validate_pool_file(name)
            if target is None:
                self._redirect(f"{'/lab' if mode == 'lab' else '/'}?flash={quote('删除失败：文件名不合法或不存在')}")
                return
            try:
                target.unlink()
                self._redirect(f"{'/lab' if mode == 'lab' else '/'}?flash={quote(f'已删除 {name}')}")
            except OSError as exc:
                self._redirect(f"{'/lab' if mode == 'lab' else '/'}?flash={quote(f'删除失败：{exc}')}")
            return

        if self.path != "/run":
            self._write_html("<h1>未找到页面</h1>", status=404)
            return

        # Refuse pathologically-large POST bodies before allocating memory.
        try:
            total_len = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            total_len = 0
        if total_len > MAX_REQUEST_BODY_BYTES:
            self._write_html(
                f"<h1>上传过大</h1>"
                f"<p>单次请求体不得超过 {_format_size(MAX_REQUEST_BODY_BYTES)}。</p>",
                status=413,
            )
            return

        content_type = self.headers.get("Content-Type", "")
        uploaded_saved: List[str] = []
        rejected_uploads: List[str] = []
        form: Dict[str, Any]
        existing_selected: List[str] = []

        if "multipart/form-data" in content_type.lower():
            body = self.rfile.read(total_len)
            boundary = b""
            m = re.search(r"boundary=([^\s;]+)", content_type, flags=re.I)
            if m:
                boundary = m.group(1).strip('"').encode("utf-8", "replace")
            fields, file_parts = _parse_multipart(body, boundary)
            uploaded_saved, rejected_uploads = _store_uploaded_files(file_parts)
            existing_selected = list(fields.get("existing_files", []))

            def _first(name: str, default: str = "") -> str:
                vs = fields.get(name) or []
                return vs[0] if vs else default

            form = {
                "ui_mode": _first("ui_mode", "prod"),
                "output_dir": _first("output_dir", "outputs"),
                "topic_mode": _first("topic_mode", "auto"),
                "web_enrichment_mode": _first("web_enrichment_mode", "auto"),
                "enable_web_enrichment": "enable_web_enrichment" in fields,
                "export_docx": "export_docx" in fields,
                "keypoint_min_confidence": _first("keypoint_min_confidence", "0.0"),
                "keypoint_max_points": _first("keypoint_max_points", "12"),
            }
        else:
            payload = self.rfile.read(total_len).decode("utf-8", errors="replace")
            form_raw = parse_qs(payload, keep_blank_values=True)
            existing_selected = list(form_raw.get("existing_files", []))
            form = {
                "ui_mode": (form_raw.get("ui_mode") or ["prod"])[0],
                "output_dir": (form_raw.get("output_dir") or ["outputs"])[0],
                "topic_mode": (form_raw.get("topic_mode") or ["auto"])[0],
                "web_enrichment_mode": (form_raw.get("web_enrichment_mode") or ["auto"])[0],
                "enable_web_enrichment": "enable_web_enrichment" in form_raw,
                "export_docx": "export_docx" in form_raw,
                "keypoint_min_confidence": (form_raw.get("keypoint_min_confidence") or ["0.0"])[0],
                "keypoint_max_points": (form_raw.get("keypoint_max_points") or ["12"])[0],
            }

        # Resolve existing pool selections to absolute paths (skip anything
        # that fails the pool validator -- user may have deleted a file
        # between render and submit).
        is_lab_mode = str(form.get("ui_mode", "prod")).strip().lower() == "lab"
        pool_paths: List[str] = []
        for sel_name in existing_selected:
            resolved = _validate_pool_file(sel_name)
            if resolved is not None:
                pool_paths.append(str(resolved))

        # De-duplicate by resolved absolute path so a file that is both
        # newly uploaded and selected from the pool is not processed twice.
        all_input_paths: List[str] = []
        seen_abs: set[str] = set()
        for path in list(uploaded_saved) + pool_paths:
            abs_key = str(Path(path).resolve())
            if abs_key in seen_abs:
                continue
            seen_abs.add(abs_key)
            all_input_paths.append(path)

        # Highlight newly-uploaded files + already-selected pool items on
        # the re-render so user sees what just happened.
        pool_selected_after = {Path(p).name for p in (list(uploaded_saved) + pool_paths)}

        try:
            # Surface per-file size rejections in the error banner so the
            # user understands why a file they picked is missing. We do not
            # bail here -- we still try to run the pipeline on whatever did
            # get saved.
            preamble_notes: List[str] = []
            if rejected_uploads:
                preamble_notes.append(
                    "以下文件超过单文件大小上限 "
                    f"{_format_size(MAX_FILE_SIZE_BYTES)}，已拒收：\n- "
                    + "\n- ".join(rejected_uploads)
                )

            # Enforce per-run count ceilings.
            image_count = sum(
                1 for p in all_input_paths if Path(p).suffix.lower() in IMAGE_SUFFIXES
            )
            if image_count > MAX_IMAGE_COUNT_PER_RUN:
                raise ValueError(
                    f"图片文件过多（{image_count} 张）。"
                    f"单次最多 {MAX_IMAGE_COUNT_PER_RUN} 张图片（OCR 耗时长）。"
                    "请在文件池中取消部分勾选后再试。"
                )
            if len(all_input_paths) > MAX_TOTAL_FILES_PER_RUN:
                raise ValueError(
                    f"文件总数过多（{len(all_input_paths)}）。"
                    f"单次最多 {MAX_TOTAL_FILES_PER_RUN} 个文件。"
                    "请取消部分勾选后再试。"
                )

            files = collect_input_files(all_input_paths)
            if not files:
                msg = (
                    "未识别到可处理的文件，请确认扩展名为 txt/md/pdf/docx 或已安装 OCR 环境的 png/jpg/jpeg。"
                    if all_input_paths
                    else "未选择任何文件：请上传新文件，或在下方\"已上传文件池\"中勾选。"
                )
                if preamble_notes:
                    msg = msg + "\n\n" + "\n\n".join(preamble_notes)
                raise ValueError(msg)

            try:
                kp_min = float(form["keypoint_min_confidence"] or 0.0)
            except (TypeError, ValueError):
                kp_min = 0.0
            try:
                kp_max = int(form["keypoint_max_points"] or 12)
            except (TypeError, ValueError):
                kp_max = 12

            result = run_pipeline(
                files,
                output_dir=str(_resolve_output_dir(str(form.get("output_dir", "")))),
                topic_mode=str(form["topic_mode"] or "auto"),
                web_enrichment_enabled=bool(form["enable_web_enrichment"]),
                web_enrichment_mode=str(form["web_enrichment_mode"] or "auto"),
                export_docx=bool(form["export_docx"]),
                keypoint_min_confidence=kp_min,
                keypoint_max_points=kp_max,
                notifier=None,
            )
            # If some uploads were rejected on size, make that visible even
            # on the success page -- attach a pipeline_note.
            if preamble_notes:
                existing_notes = result.get("pipeline_notes") or []
                result["pipeline_notes"] = existing_notes + [
                    "UI upload size limit: " + "; ".join(rejected_uploads)
                ]
            body = _render_page(
                form=form,
                result=result,
                uploaded_files=uploaded_saved,
                pool_selected=pool_selected_after,
                lab_mode=is_lab_mode,
            )
            self._write_html(body)
        except ValueError as exc:
            # User-facing validation (empty upload, wrong type, limits).
            err_text = str(exc)
            if rejected_uploads and "超过单文件大小上限" not in err_text:
                err_text += "\n另有超限文件被拒收：\n- " + "\n- ".join(rejected_uploads)
            body = _render_page(
                form=form,
                error=f"输入错误: {err_text}",
                uploaded_files=uploaded_saved,
                pool_selected=pool_selected_after,
                lab_mode=is_lab_mode,
            )
            self._write_html(body, status=400)
        except Exception as exc:
            # Unexpected pipeline error -- still 500 but keep UI alive.
            body = _render_page(
                form=form,
                error=f"流水线异常: {exc}",
                uploaded_files=uploaded_saved,
                pool_selected=pool_selected_after,
                lab_mode=is_lab_mode,
            )
            self._write_html(body, status=500)


def main() -> None:
    _load_local_env(".env")

    parser = argparse.ArgumentParser(description="KnowledgeHarness 简易本地界面")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", default=8765, type=int, help="监听端口")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), _Handler)
    print(f"简易界面已启动: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
