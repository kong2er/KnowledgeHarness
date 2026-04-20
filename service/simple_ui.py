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


def _store_uploaded_files(items: List[Tuple[str, str, bytes]]) -> List[str]:
    """Persist uploaded file parts to `uploads/ui_uploads/` and return paths.

    Args:
        items: (field_name, original_filename, raw_bytes) triples from the
            multipart parser. Parts whose field_name is not `upload_files`
            are ignored.

    Empty payloads are skipped so the user re-submitting the form without
    picking a new file does not create a zero-byte placeholder.
    """
    if not items:
        return []
    upload_dir = Path("uploads") / "ui_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    saved: List[str] = []
    for field_name, filename, data in items:
        if field_name != "upload_files":
            continue
        if not data:
            continue
        base = _safe_filename(filename)
        target = upload_dir / base
        stem = target.stem
        suffix = target.suffix
        idx = 1
        while target.exists():
            target = upload_dir / f"{stem}_{idx}{suffix}"
            idx += 1
        target.write_bytes(data)
        saved.append(str(target))
    return saved


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
    """Render a download anchor iff `abs_path` is inside outputs/;
    otherwise render just the path as escaped text.
    """
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
    # Output lives outside the whitelisted directory -- cannot safely serve.
    return (
        f'<p><strong>{html.escape(label)}:</strong> {escaped_path} '
        f'<span class="hint">(不在 outputs/ 下，无法通过浏览器下载，请手动打开路径)</span></p>'
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
) -> str:
    output_dir = str(form.get("output_dir", "outputs"))
    topic_mode = str(form.get("topic_mode", "auto"))
    enable_web = bool(form.get("enable_web_enrichment", False))
    web_mode = str(form.get("web_enrichment_mode", "auto"))
    kp_min = str(form.get("keypoint_min_confidence", "0.0"))
    kp_max = str(form.get("keypoint_max_points", "12"))
    export_docx = bool(form.get("export_docx", False))
    uploaded_files = uploaded_files or []

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

    error_html = (
        f'<div class="error">{html.escape(error)}</div>'
        if error
        else ""
    )
    uploaded_html = ""
    if uploaded_files:
        uploaded_html = '<div class="row"><label>本次已上传文件</label><pre>' + html.escape(
            "\n".join(uploaded_files)
        ) + "</pre></div>"

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>KnowledgeHarness 简易界面</title>
  <style>
    body {{
      margin: 0; padding: 24px; background: #f7f4ef; color: #1f2937;
      font-family: "IBM Plex Sans", "Noto Sans", sans-serif;
    }}
    .wrap {{ max-width: 1100px; margin: 0 auto; }}
    .card {{
      background: #ffffff; border: 1px solid #e5e7eb; border-radius: 12px;
      padding: 16px; margin-bottom: 16px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.04);
    }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    .grid-single {{ display: grid; grid-template-columns: 1fr; gap: 12px; }}
    .summary .summary-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
    .summary-grid > div {{ background: #fafafa; border: 1px solid #eef2ff; border-radius: 8px; padding: 10px; }}
    label {{ display: block; margin-bottom: 6px; font-weight: 600; }}
    input[type=text], input[type=number], textarea, select {{
      width: 100%; box-sizing: border-box; padding: 8px;
      border: 1px solid #d1d5db; border-radius: 8px; background: #fff;
    }}
    textarea {{ min-height: 100px; }}
    .row {{ margin-bottom: 12px; }}
    button {{
      background: #0f766e; color: #fff; border: 0; border-radius: 8px;
      padding: 10px 14px; font-weight: 600; cursor: pointer;
    }}
    button[disabled] {{ background: #94a3b8; cursor: progress; }}
    .button-link {{
      display: inline-block; text-decoration: none; margin-left: 8px;
      background: #1d4ed8; color: #fff; border-radius: 8px;
      padding: 10px 14px; font-weight: 600;
    }}
    pre {{
      white-space: pre-wrap; word-break: break-word;
      background: #f3f4f6; border-radius: 8px; padding: 10px;
      border: 1px solid #e5e7eb;
      max-height: 480px; overflow-y: auto;
    }}
    .error {{
      background: #fef2f2; color: #991b1b; border: 1px solid #fecaca;
      padding: 10px; border-radius: 8px; margin-bottom: 12px;
    }}
    .status {{
      background: #fff7ed; color: #9a3412; border: 1px solid #fdba74;
      padding: 10px; border-radius: 8px; margin-bottom: 12px;
    }}
    .hint {{ color: #4b5563; font-size: 13px; }}
    details {{
      border: 1px solid #e5e7eb; border-radius: 8px; padding: 10px; background: #fafafa;
    }}
    details > summary {{
      cursor: pointer; font-weight: 600; margin-bottom: 8px;
    }}
    .badge {{ display: inline-block; padding: 3px 10px; border-radius: 999px; font-weight: 600; font-size: 13px; }}
    .badge-ok {{ background: #ecfdf5; color: #065f46; border: 1px solid #a7f3d0; }}
    .badge-warn {{ background: #fef3c7; color: #92400e; border: 1px solid #fde68a; }}
    table.mini {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    table.mini th, table.mini td {{ border-bottom: 1px solid #e5e7eb; padding: 4px 6px; text-align: left; }}
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
          status.textContent = "流水线执行中：解析 → 切分 → 主题粗分类 → 内容分类 → 总结 → 重点 → 补充 → 校验 → 导出…";
          wrap.insertBefore(status, wrap.firstChild);
        }}
      }});
    }});
  </script>
</head>
<body>
  <div class="wrap">
    <section class="card">
      <h1>KnowledgeHarness 简易界面</h1>
      <p class="hint">请上传文件进行处理。分类模式、阈值等在"高级选项"中设置。</p>
      {error_html}
      <form method="post" action="/run" enctype="multipart/form-data">
        <div class="row">
          <label for="upload_files">上传文件（可多选；支持 txt/md/pdf/docx 及可选 OCR 图片 png/jpg/jpeg）</label>
          <input id="upload_files" type="file" name="upload_files" multiple />
        </div>
        {uploaded_html}

        <div class="grid-single">
          <div class="row">
            <label for="output_dir">输出目录</label>
            <input id="output_dir" type="text" name="output_dir" value="{html.escape(output_dir)}" />
            <p class="hint">仅当输出位于 <code>outputs/</code> 之下时，UI 才会提供下载链接；否则只显示绝对路径。</p>
          </div>
          <div class="row">
            <label><input type="checkbox" name="enable_web_enrichment" {_checked(enable_web)} /> 启用 Web 补充</label>
            <label><input type="checkbox" name="export_docx" {_checked(export_docx)} /> 同时导出 Word（.docx）</label>
          </div>
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
        <br />
        <button type="submit">运行流水线</button>
        <a class="button-link" href="/settings">API 设置</a>
      </form>
    </section>
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
  <title>API 设置</title>
  <style>
    body {{
      margin: 0; padding: 24px; background: #f7f4ef; color: #1f2937;
      font-family: "IBM Plex Sans", "Noto Sans", sans-serif;
    }}
    .wrap {{ max-width: 900px; margin: 0 auto; }}
    .card {{
      background: #ffffff; border: 1px solid #e5e7eb; border-radius: 12px;
      padding: 16px; margin-bottom: 16px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.04);
    }}
    label {{ display: block; margin-bottom: 6px; font-weight: 600; }}
    input[type=text], input[type=password] {{
      width: 100%; box-sizing: border-box; padding: 8px;
      border: 1px solid #d1d5db; border-radius: 8px; background: #fff;
      margin-bottom: 6px;
    }}
    .row {{ margin-bottom: 18px; }}
    button {{
      background: #0f766e; color: #fff; border: 0; border-radius: 8px;
      padding: 10px 14px; font-weight: 600; cursor: pointer;
    }}
    .back {{
      display: inline-block; margin-left: 8px; text-decoration: none;
      background: #1d4ed8; color: #fff; border-radius: 8px;
      padding: 10px 14px; font-weight: 600;
    }}
    .hint {{ color: #4b5563; font-size: 13px; }}
    .status {{ display: inline-block; padding: 2px 10px; border-radius: 999px; background: #f1f5f9; font-size: 13px; margin-bottom: 6px; }}
    .error {{
      background: #fef2f2; color: #991b1b; border: 1px solid #fecaca;
      padding: 10px; border-radius: 8px; margin-bottom: 12px;
    }}
    .ok {{
      background: #ecfdf5; color: #065f46; border: 1px solid #a7f3d0;
      padding: 10px; border-radius: 8px; margin-bottom: 12px;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="card">
      <h1>API 设置</h1>
      <p class="hint">保存后将写入项目根目录 <code>.env</code>。
      为防止泄露，当前值不会回填输入框。<strong>留空 = 保持原值</strong>；若要更新请输入新值；若要清空请手动编辑 <code>.env</code>。
      中间处理阶段默认共用这一套 API 设置；若需按模块覆盖（TOPIC/WEB_ENRICHMENT 专用 key），请直接编辑 <code>.env</code>（参考 <code>.env.example</code>）。</p>
      {error_html}
      {success_html}
      <form method="post" action="/settings" autocomplete="off">
        <div class="row">
          <label for="KNOWLEDGEHARNESS_API_URL">统一 API 地址（KNOWLEDGEHARNESS_API_URL）</label>
          <span class="status">{html.escape(statuses['KNOWLEDGEHARNESS_API_URL'])}</span>
          <input id="KNOWLEDGEHARNESS_API_URL" type="text" name="KNOWLEDGEHARNESS_API_URL" value="" placeholder="留空保持当前值" autocomplete="off" />
        </div>

        <div class="row">
          <label for="KNOWLEDGEHARNESS_API_KEY">统一 API 密钥（KNOWLEDGEHARNESS_API_KEY）</label>
          <span class="status">{html.escape(statuses['KNOWLEDGEHARNESS_API_KEY'])}</span>
          <input id="KNOWLEDGEHARNESS_API_KEY" type="password" name="KNOWLEDGEHARNESS_API_KEY" value="" placeholder="留空保持当前值" autocomplete="new-password" />
        </div>

        <button type="submit">保存 API 设置</button>
        <a class="back" href="/">返回主界面</a>
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

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        route = parsed.path
        if route == "/":
            self._write_html(_render_page(form={}))
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

        if self.path != "/run":
            self._write_html("<h1>未找到页面</h1>", status=404)
            return

        content_type = self.headers.get("Content-Type", "")
        uploaded_saved: List[str] = []
        form: Dict[str, Any]

        if "multipart/form-data" in content_type.lower():
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            boundary = b""
            m = re.search(r"boundary=([^\s;]+)", content_type, flags=re.I)
            if m:
                boundary = m.group(1).strip('"').encode("utf-8", "replace")
            fields, file_parts = _parse_multipart(body, boundary)
            uploaded_saved = _store_uploaded_files(file_parts)

            def _first(name: str, default: str = "") -> str:
                vs = fields.get(name) or []
                return vs[0] if vs else default

            form = {
                "output_dir": _first("output_dir", "outputs"),
                "topic_mode": _first("topic_mode", "auto"),
                "web_enrichment_mode": _first("web_enrichment_mode", "auto"),
                "enable_web_enrichment": "enable_web_enrichment" in fields,
                "export_docx": "export_docx" in fields,
                "keypoint_min_confidence": _first("keypoint_min_confidence", "0.0"),
                "keypoint_max_points": _first("keypoint_max_points", "12"),
            }
        else:
            length = int(self.headers.get("Content-Length", "0"))
            payload = self.rfile.read(length).decode("utf-8", errors="replace")
            form_raw = parse_qs(payload, keep_blank_values=True)
            form = {
                "output_dir": (form_raw.get("output_dir") or ["outputs"])[0],
                "topic_mode": (form_raw.get("topic_mode") or ["auto"])[0],
                "web_enrichment_mode": (form_raw.get("web_enrichment_mode") or ["auto"])[0],
                "enable_web_enrichment": "enable_web_enrichment" in form_raw,
                "export_docx": "export_docx" in form_raw,
                "keypoint_min_confidence": (form_raw.get("keypoint_min_confidence") or ["0.0"])[0],
                "keypoint_max_points": (form_raw.get("keypoint_max_points") or ["12"])[0],
            }

        try:
            files = collect_input_files(list(uploaded_saved))
            if not files:
                msg = (
                    "未识别到可处理的上传文件，请检查文件格式（支持 txt/md/pdf/docx 及可选 OCR 图片）。"
                    if uploaded_saved
                    else "未上传任何文件，请先选择文件。"
                )
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
                output_dir=str(form["output_dir"] or "outputs"),
                topic_mode=str(form["topic_mode"] or "auto"),
                web_enrichment_enabled=bool(form["enable_web_enrichment"]),
                web_enrichment_mode=str(form["web_enrichment_mode"] or "auto"),
                export_docx=bool(form["export_docx"]),
                keypoint_min_confidence=kp_min,
                keypoint_max_points=kp_max,
                notifier=None,
            )
            body = _render_page(form=form, result=result, uploaded_files=uploaded_saved)
            self._write_html(body)
        except ValueError as exc:
            # User-facing validation (empty upload, wrong type).
            body = _render_page(
                form=form,
                error=f"输入错误: {exc}",
                uploaded_files=uploaded_saved,
            )
            self._write_html(body, status=400)
        except Exception as exc:
            # Unexpected pipeline error -- still 500 but keep UI alive.
            body = _render_page(
                form=form,
                error=f"流水线异常: {exc}",
                uploaded_files=uploaded_saved,
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
