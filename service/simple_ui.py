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
import contextlib
import errno
import html
import json
import mimetypes
import os
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import parse_qs, quote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import collect_input_files, run_pipeline
from tools.pipeline_runtime import (
    build_pipeline_run_kwargs,
    is_any_api_configured,
    load_local_env,
)

ENV_PATH = Path(".env")
API_PROFILES_PATH = ROOT / "config" / "api_profiles.json"
OUTPUT_WHITELIST_ROOT = (ROOT / "outputs").resolve()
ACTIVE_PROFILE_ENV_KEY = "KNOWLEDGEHARNESS_ACTIVE_API_PROFILE"

# Unified API keys shown in the "主设置" section of /settings.
API_ENV_KEYS = [
    "KNOWLEDGEHARNESS_API_URL",
    "KNOWLEDGEHARNESS_API_KEY",
]
# Per-module override keys shown in the collapsed "按模块覆盖" section.
# They fall back to the unified keys when left blank at runtime
# (see tools/topic_coarse_classify.py and tools/web_enrichment.py).
MODULE_OVERRIDE_KEYS = [
    ("TOPIC_CLASSIFIER_API_URL", "url", "Topic 分类 · API 地址"),
    ("TOPIC_CLASSIFIER_API_KEY", "password", "Topic 分类 · 密钥"),
    ("TOPIC_CLASSIFIER_API_TEMPLATE", "url", "Topic 分类 · 模板文件路径"),
    ("IMAGE_OCR_API_URL", "url", "图片 OCR · API 地址"),
    ("IMAGE_OCR_API_KEY", "password", "图片 OCR · 密钥"),
    ("IMAGE_OCR_API_TEMPLATE", "url", "图片 OCR · 模板文件路径"),
    ("WEB_ENRICHMENT_API_URL", "url", "Web 补充 · API 地址"),
    ("WEB_ENRICHMENT_API_KEY", "password", "Web 补充 · 密钥"),
    ("WEB_ENRICHMENT_API_TEMPLATE", "url", "Web 补充 · 模板文件路径"),
]
ALL_SETTINGS_KEYS = API_ENV_KEYS + [k for k, _, _ in MODULE_OVERRIDE_KEYS]
PROFILE_ENV_KEYS = list(ALL_SETTINGS_KEYS)

LAB_ENABLED = os.getenv("KH_UI_ENABLE_LAB", "0").strip() == "1"
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


def _write_env_pairs(
    updates: Dict[str, str],
    path: Path = ENV_PATH,
    clears: "set[str] | None" = None,
) -> Tuple[List[str], List[str]]:
    """Persist changes to .env.

    Args:
        updates: {key: value} — only non-empty values are written. Empty
                 values are treated as "keep the previous value" so the
                 UI can render blank password inputs without clobbering
                 existing secrets.
        clears:  set of keys that the user explicitly asked to clear.
                 For each such key the line is rewritten as `KEY=` (empty
                 value preserved, comment/structure untouched).

    Returns:
        (touched_keys, cleared_keys) — callers surface a flash message
        per list so the user sees exactly what changed.
    """
    clears = set(clears or [])
    existing_lines: List[str] = []
    if path.exists() and path.is_file():
        existing_lines = path.read_text(encoding="utf-8").splitlines()

    # Drop update entries that are empty AND not explicitly cleared so
    # the old value is preserved.
    effective = {k: v for k, v in updates.items() if v and k not in clears}
    if not effective and not clears:
        return [], []

    touched: set = set()
    cleared: set = set()
    new_lines: List[str] = []
    for raw in existing_lines:
        s = raw.strip()
        if not s or s.startswith("#") or "=" not in raw:
            new_lines.append(raw)
            continue
        key = raw.split("=", 1)[0].strip()
        if key in clears:
            new_lines.append(f"{key}=")
            cleared.add(key)
        elif key in effective:
            new_lines.append(f"{key}={effective[key]}")
            touched.add(key)
        else:
            new_lines.append(raw)

    # Append keys that did not already exist in the file.
    for k, v in effective.items():
        if k not in touched:
            new_lines.append(f"{k}={v}")
            touched.add(k)
    for k in clears:
        if k not in cleared:
            new_lines.append(f"{k}=")
            cleared.add(k)

    if not new_lines:
        new_lines = [f"{k}={v}" for k, v in effective.items()]
        new_lines.extend(f"{k}=" for k in clears)
    path.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")

    # Reflect changes into the running process's env so the pipeline
    # picks them up without requiring a restart.
    for k, v in effective.items():
        os.environ[k] = v
    for k in clears:
        # "Clearing" in the running process means setting empty string,
        # so downstream `os.getenv(k, "").strip()` treats it as unset.
        os.environ[k] = ""

    return list(touched), list(cleared)


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


def _sanitize_profile_name(raw: str) -> str:
    name = (raw or "").strip()
    # Keep profile names safe/simple for HTML rendering + env hints.
    return re.sub(r"[\r\n\t]", " ", name)[:64]


def _load_api_profiles(path: Path = API_PROFILES_PATH) -> Dict[str, Any]:
    """Load profile store: {"active_profile": str, "profiles": [{...}], ...}.

    File is optional; malformed content degrades to an empty profile set.
    """
    empty: Dict[str, Any] = {"active_profile": "", "profiles": []}
    if not path.exists() or not path.is_file():
        return empty
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return empty
    if not isinstance(raw, dict):
        return empty
    raw_profiles = raw.get("profiles")
    if not isinstance(raw_profiles, list):
        raw_profiles = []
    profiles: List[Dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_profiles:
        if not isinstance(item, dict):
            continue
        name = _sanitize_profile_name(str(item.get("name", "")))
        if not name or name in seen:
            continue
        cleaned: Dict[str, str] = {"name": name}
        for k in PROFILE_ENV_KEYS:
            cleaned[k] = str(item.get(k, "") or "").strip()
        profiles.append(cleaned)
        seen.add(name)
    active = _sanitize_profile_name(str(raw.get("active_profile", "") or ""))
    if active not in seen:
        active = ""
    return {"active_profile": active, "profiles": profiles}


def _save_api_profiles(payload: Dict[str, Any], path: Path = API_PROFILES_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _profile_names(payload: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for p in payload.get("profiles", []) or []:
        name = _sanitize_profile_name(str(p.get("name", "")))
        if name:
            out.append(name)
    return out


def _profile_by_name(payload: Dict[str, Any], name: str) -> Dict[str, str] | None:
    target = _sanitize_profile_name(name)
    if not target:
        return None
    for p in payload.get("profiles", []) or []:
        if _sanitize_profile_name(str(p.get("name", ""))) == target:
            return p
    return None


def _profile_updates(profile: Dict[str, Any]) -> Dict[str, str]:
    return {k: str(profile.get(k, "") or "").strip() for k in PROFILE_ENV_KEYS}


@contextlib.contextmanager
def _temporary_profile_env(profile: Dict[str, Any]) -> Any:
    """Apply a profile to process env for one pipeline run, then restore."""
    snapshot = {k: os.getenv(k, "") for k in PROFILE_ENV_KEYS}
    try:
        values = _profile_updates(profile)
        for k, v in values.items():
            os.environ[k] = v
        yield
    finally:
        for k, old in snapshot.items():
            os.environ[k] = old


def _api_status_chip() -> str:
    """Return an HTML chip describing whether any API URL is configured.

    Rendered at page-top so users know at a glance whether the run will
    stay fully local or will call out to an external service. Clickable
    so one click lands on /settings.
    """
    active_profile = os.getenv(ACTIVE_PROFILE_ENV_KEY, "").strip()
    if is_any_api_configured():
        label = "API 已配置"
        tone = "api-chip on"
        hint = "点击调整密钥与按模块覆盖"
        if active_profile:
            hint += f"（当前档案：{active_profile}）"
    else:
        label = "本地模式"
        tone = "api-chip off"
        hint = "无任何 API 配置，所有步骤在本地完成"
    return (
        f'<a class="{tone}" href="/settings" title="{html.escape(hint)}">'
        f'<span class="api-chip-dot"></span>{label}</a>'
    )


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
        # `/download` only supports direct children under outputs root.
        if p.parent != OUTPUT_WHITELIST_ROOT:
            return ""
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
            <li>图片 API 尝试: <strong>{ingestion.get('image_api_attempted', 0)}</strong></li>
            <li>图片 API 生效: <strong>{ingestion.get('image_api_succeeded', 0)}</strong></li>
            <li>图片增强覆盖: <strong>{ingestion.get('image_api_enhanced', 0)}</strong></li>
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
    enable_api_assist = bool(form.get("enable_api_assist", False))
    web_mode = str(form.get("web_enrichment_mode", "auto"))
    kp_min = str(form.get("keypoint_min_confidence", "0.0"))
    kp_max = str(form.get("keypoint_max_points", "12"))
    validation_profile = str(form.get("validation_profile", "strict"))
    export_docx = bool(form.get("export_docx", False))

    profiles_payload = _load_api_profiles()
    profile_names = _profile_names(profiles_payload)
    default_profile = (
        str(form.get("api_profile", "")).strip()
        or os.getenv(ACTIVE_PROFILE_ENV_KEY, "").strip()
        or str(profiles_payload.get("active_profile", "")).strip()
    )
    if default_profile not in profile_names:
        default_profile = ""
    api_profile = default_profile

    has_any_api = is_any_api_configured()
    image_enhance_mode = (os.getenv("IMAGE_OCR_ENHANCE_MODE", "auto") or "auto").strip().lower()
    image_enhance_desc = {
        "fallback_only": "仅失败回退（本地 OCR 失败/空文本才调用 API）",
        "auto": "自动增强（本地低质量时调用 API 并择优）",
        "prefer_api": "优先 API（启用 API 协助时优先用 API 结果）",
    }.get(image_enhance_mode, "自动增强（本地低质量时调用 API 并择优）")

    uploaded_files = uploaded_files or []
    pool_selected = pool_selected or set()

    resolved_output_dir = _resolve_output_dir(output_dir)
    output_browser_base = "/lab/outputs" if lab_mode else "/outputs"
    output_browser_link = f"{output_browser_base}?dir={quote(str(resolved_output_dir))}"

    # ---- result / status model for right panel ----
    export_paths: Dict[str, Any] = {}
    md_path = ""
    json_path = ""
    docx_path = ""
    final_doc_preview = ""
    overview: Dict[str, Any] = {}
    ingestion: Dict[str, Any] = {}
    validation: Dict[str, Any] = {}
    warnings: List[str] = []
    pipeline_notes: List[str] = []
    topic_output: Dict[str, Any] = {}
    topic_stats: Dict[str, Any] = {}
    topic_items: List[Dict[str, Any]] = []

    if result is not None:
        export_paths = result.get("export_paths", {}) or {}
        md_path = str(export_paths.get("md_path", "")).strip()
        json_path = str(export_paths.get("json_path", "")).strip()
        docx_path = str(export_paths.get("docx_path", "")).strip()
        overview = result.get("overview", {}) or {}
        ingestion = overview.get("ingestion_summary", {}) or {}
        validation = result.get("validation", {}) or {}
        warnings = [str(w) for w in (validation.get("warnings", []) or [])]
        pipeline_notes = [str(x) for x in (result.get("pipeline_notes", []) or [])]
        topic_output = result.get("topic_classification", {}) or {}
        topic_stats = topic_output.get("stats", {}) or {}
        topic_items = topic_output.get("items", []) or []

        if md_path:
            p = Path(md_path)
            if p.exists() and p.is_file():
                text_md = p.read_text(encoding="utf-8", errors="replace")
                final_doc_preview = text_md[:10000]
                if len(text_md) > 10000:
                    final_doc_preview += "\n\n…（已截断，请使用“打开结果文件/下载”获取完整文件）"
            else:
                final_doc_preview = "未找到最终文档文件，请确认本次运行已成功导出。"
        else:
            final_doc_preview = "本次运行未返回最终文档路径。"

    detected = int(ingestion.get("detected", 0) or 0)
    succeeded = int(ingestion.get("succeeded", 0) or 0)
    failed = int(ingestion.get("failed", 0) or 0)
    empty_extracted = int(ingestion.get("empty_extracted", 0) or 0)

    if error:
        stage_title = "执行失败"
        stage_desc = "本次运行被中断，请根据错误提示修正输入后重试。"
    elif result is None:
        stage_title = "等待开始"
        stage_desc = "请选择资料并点击“开始整理”。"
    elif warnings:
        stage_title = "已完成（含告警）"
        stage_desc = "笔记已导出，可先查看结果，再根据告警决定是否重跑。"
    else:
        stage_title = "已完成"
        stage_desc = "笔记已导出，可直接查看结果文件。"

    stage_steps = [
        "读取资料",
        "切分",
        "主题粗分类",
        "内容分类",
        "阶段总结",
        "校验",
        "导出",
    ]
    if result is not None:
        stage_steps_html = "".join(
            f'<li class="step done"><span class="dot"></span>{html.escape(step)}</li>'
            for step in stage_steps
        )
    elif error:
        stage_steps_html = (
            '<li class="step error"><span class="dot"></span>运行中断（请看下方错误）</li>'
            + "".join(
                f'<li class="step pending"><span class="dot"></span>{html.escape(step)}</li>'
                for step in stage_steps
            )
        )
    else:
        stage_steps_html = "".join(
            f'<li class="step pending"><span class="dot"></span>{html.escape(step)}</li>'
            for step in stage_steps
        )

    warnings_html = "".join(f"<li>{html.escape(w)}</li>" for w in warnings[:6]) or "<li>（无）</li>"
    notes_html = "".join(f"<li>{html.escape(n)}</li>" for n in pipeline_notes[:10]) or "<li>（无）</li>"

    topic_top = topic_stats.get("counts_by_label", {}) if isinstance(topic_stats.get("counts_by_label", {}), dict) else {}
    topic_counts_html = "".join(
        f"<li>{html.escape(str(k))}: <strong>{int(v)}</strong></li>"
        for k, v in topic_top.items()
    ) or "<li>（无）</li>"
    topic_item_html = "".join(
        f"<li>{html.escape(str(it.get('source_name') or 'unknown'))} → "
        f"<strong>{html.escape(str(it.get('topic_label') or 'unknown_topic'))}</strong>"
        f"（conf={html.escape(str(it.get('confidence') or '0'))}，{'API' if it.get('used_api') else 'local'}）</li>"
        for it in topic_items[:8]
    ) or "<li>（无）</li>"

    flash_html = f'<div class="ok">{html.escape(flash)}</div>' if flash else ""
    error_html = f'<div class="error">{html.escape(error)}</div>' if error else ""

    # ---- file pool ----
    pool_items = _list_uploaded_pool()
    from collections import Counter
    import time as _time

    ext_counter: Counter = Counter()
    pool_rows_html: List[str] = []
    for name, size, mtime in pool_items:
        ext = Path(name).suffix.lower().lstrip(".") or "(无后缀)"
        ext_counter[ext] += 1
        date_str = _time.strftime("%Y-%m-%d %H:%M", _time.localtime(mtime))
        is_image = ext in {"png", "jpg", "jpeg"}
        pill_class = "type-pill type-img" if is_image else "type-pill"
        escaped = html.escape(name)
        checked = "checked" if name in pool_selected else ""
        pick_status = "本次将处理" if checked else "待选择"
        pick_status_class = "file-status selected" if checked else "file-status"
        pool_rows_html.append(
            "<li class=\"pool-row\">"
            "<label class=\"pool-pick\">"
            f'<input type=\"checkbox\" name=\"existing_files\" value=\"{escaped}\" {checked} form=\"runForm\" />'
            f'<span class=\"{pill_class}\">{html.escape(ext)}</span>'
            f'<span class=\"pool-name\">{escaped}</span>'
            f'<span class=\"pool-meta\">{_format_size(size)} · {date_str}</span>'
            f'<span class=\"{pick_status_class}\">{pick_status}</span>'
            "</label>"
            '<form method=\"post\" action=\"/uploads/remove\" class=\"pool-remove\">'
            f'<input type=\"hidden\" name=\"name\" value=\"{escaped}\" />'
            f'<input type=\"hidden\" name=\"ui_mode\" value=\"{"lab" if lab_mode else "prod"}\" />'
            '<button type=\"submit\" class=\"link-btn\" title=\"从文件池移除\">删除</button>'
            "</form>"
            "</li>"
        )

    breakdown_parts = [f".{ext} × {count}" for ext, count in sorted(ext_counter.items(), key=lambda kv: (-kv[1], kv[0]))]
    breakdown_line = " · ".join(breakdown_parts) if breakdown_parts else "当前暂无文件"

    image_total = ext_counter.get("png", 0) + ext_counter.get("jpg", 0) + ext_counter.get("jpeg", 0)
    upload_info = ""
    if uploaded_files:
        upload_info = f"本次新增上传 {len(uploaded_files)} 个文件。"

    pool_warns: List[str] = []
    if image_total > MAX_IMAGE_COUNT_PER_RUN:
        pool_warns.append(
            f"当前池中有 {image_total} 张图片，超过单次处理上限 {MAX_IMAGE_COUNT_PER_RUN} 张，请勾选部分后再运行。"
        )
    if len(pool_items) > MAX_TOTAL_FILES_PER_RUN:
        pool_warns.append(
            f"当前池中文件总数 {len(pool_items)} 超过单次处理上限 {MAX_TOTAL_FILES_PER_RUN} 个，请先清理或少量勾选。"
        )
    pool_warn_html = "".join(f'<p class="pool-warn">{html.escape(msg)}</p>' for msg in pool_warns)

    if pool_items:
        pool_list_html = f"""
        <section class="card left-card">
          <div class="card-head">
            <h2>文件列表 <span class="pool-count">{len(pool_items)}</span></h2>
            <form method="post" action="/uploads/clear" class="pool-clear">
              <input type="hidden" name="ui_mode" value="{"lab" if lab_mode else "prod"}" />
              <button type="submit" class="tertiary danger">清空列表</button>
            </form>
          </div>
          <p class="hint">{html.escape(breakdown_line)}</p>
          <p class="hint">{html.escape(upload_info)}</p>
          {pool_warn_html}
          <ul class="pool-list">{''.join(pool_rows_html)}</ul>
        </section>
        """
    else:
        pool_list_html = """
        <section class="card left-card">
          <h2>文件列表</h2>
          <p class="empty">还没有文件。请先点击“选择文件”或“选择文件夹”。</p>
        </section>
        """

    # ---- mode-specific controls ----
    profile_select_html = ""
    if profile_names:
        options = ['<option value="">使用当前环境（不指定档案）</option>']
        for name in profile_names:
            options.append(f'<option value="{html.escape(name)}" {_selected(api_profile, name)}>{html.escape(name)}</option>')
        profile_select_html = f"""
        <div class="row">
          <label for="api_profile">API 档案</label>
          <select id="api_profile" name="api_profile">{''.join(options)}</select>
          <p class="hint">档案在“API 设置”页维护，此处仅选择本次运行使用的档案。</p>
        </div>
        """

    api_assist_hint_html = (
        '<p class="hint">已检测到 API 配置。默认仍本地运行；勾选“启用 API 协助”后才调用外部 API。'
        f' 图片增强策略：<strong>{html.escape(image_enhance_desc)}</strong>。</p>'
        if has_any_api
        else '<p class="hint">未检测到 API 配置：当前将以本地模式运行。</p>'
    )

    prod_controls_html = """
        {profile_select_html}
        <div class="row">{api_assist_hint_html}</div>
        <div class="row inline-checks">
          <label><input type="checkbox" name="enable_api_assist" {api_assist_checked} /> 启用 API 协助（可选）</label>
          <label><input type="checkbox" name="export_docx" {docx_checked} /> 同时导出 Word（.docx）</label>
        </div>
        <div class="row">
          <label for="validation_profile">校验策略</label>
          <select id="validation_profile" name="validation_profile">
            <option value="strict" {validation_profile_strict}>严格（strict）</option>
            <option value="lenient" {validation_profile_lenient}>宽松（lenient，图片/小样本建议）</option>
          </select>
        </div>
        <input type="hidden" name="topic_mode" value="auto" />
        <input type="hidden" name="web_enrichment_mode" value="auto" />
        <input type="hidden" name="keypoint_min_confidence" value="0.0" />
        <input type="hidden" name="keypoint_max_points" value="12" />
    """.format(
        profile_select_html=profile_select_html,
        api_assist_hint_html=api_assist_hint_html,
        api_assist_checked=_checked(enable_api_assist),
        docx_checked=_checked(export_docx),
        validation_profile_strict=_selected(validation_profile, "strict"),
        validation_profile_lenient=_selected(validation_profile, "lenient"),
    )

    lab_controls_html = f"""
        {profile_select_html}
        <div class="row inline-checks">
          <label><input type="checkbox" name="enable_api_assist" {_checked(enable_api_assist)} /> 启用 API 协助</label>
          <label><input type="checkbox" name="enable_web_enrichment" {_checked(enable_web)} /> 启用 Web 补充</label>
          <label><input type="checkbox" name="export_docx" {_checked(export_docx)} /> 导出 Word（.docx）</label>
        </div>
        <details>
          <summary>高级运行参数</summary>
          <div class="grid-two">
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
              <label for="keypoint_min_confidence">关键点最小置信度（0~1）</label>
              <input id="keypoint_min_confidence" type="number" step="0.05" min="0" max="1" name="keypoint_min_confidence" value="{html.escape(kp_min)}" />
            </div>
            <div class="row">
              <label for="keypoint_max_points">关键点最大数量</label>
              <input id="keypoint_max_points" type="number" step="1" min="1" max="200" name="keypoint_max_points" value="{html.escape(kp_max)}" />
            </div>
            <div class="row">
              <label for="validation_profile">校验策略</label>
              <select id="validation_profile" name="validation_profile">
                <option value="strict" {_selected(validation_profile, "strict")}>严格（strict）</option>
                <option value="lenient" {_selected(validation_profile, "lenient")}>宽松（lenient）</option>
              </select>
            </div>
          </div>
        </details>
    """

    controls_html = lab_controls_html if lab_mode else prod_controls_html

    if lab_mode:
        lab_switch_html = '<a class="secondary-link" href="/">切换为对外视图</a>'
        submit_button_label = "运行流水线"
        page_subtitle = "调试视图：显示完整过程信息与诊断结果。"
    else:
        submit_button_label = "开始整理"
        page_subtitle = "导入学习资料，自动整理为结构化笔记。"
        if LAB_ENABLED and SHOW_LAB_LINK:
            lab_switch_html = '<a class="secondary-link" href="/lab">进入调试视图</a>'
        else:
            lab_switch_html = ""

    mode_badge = (
        '<span class="mode-badge" title="带完整诊断信息">调试视图</span>' if lab_mode else ''
    )

    md_download_chip = _render_download_button("下载 Markdown", "md", md_path)
    docx_download_chip = _render_download_button("下载 Word", "docx", docx_path)
    open_result_btn = (
        f'<a class="secondary-link" href="/download?name={html.escape(_relative_to_outputs(md_path))}" download>打开结果文件</a>'
        if _relative_to_outputs(md_path)
        else '<span class="disabled-action">打开结果文件（未生成）</span>'
    )

    result_summary_html = ""
    if result is not None:
        result_summary_html = f"""
        <section class="card right-card">
          <h2>结果摘要</h2>
          <ul class="kv-list">
            <li>处理文件数：<strong>{detected}</strong></li>
            <li>成功：<strong>{succeeded}</strong> · 失败：<strong>{failed}</strong> · 空文本：<strong>{empty_extracted}</strong></li>
            <li>校验状态：<strong>{'通过' if validation.get('is_valid') else '有告警'}</strong>（warnings: {len(warnings)}）</li>
            <li>导出状态：<strong>{'已生成' if md_path else '未生成'}</strong></li>
          </ul>
          <div class="result-actions">
            {open_result_btn}
            <a class="secondary-link" href="{html.escape(output_browser_link)}">打开输出目录</a>
          </div>
          <div class="download-row">{md_download_chip}{docx_download_chip}</div>
        </section>
        <section class="card right-card">
          <h2>主题粗分类摘要</h2>
          <p class="hint">API 协助: <strong>{topic_stats.get('used_api_count', 0)}</strong> · 降级: <strong>{topic_stats.get('degraded_count', 0)}</strong></p>
          <div class="grid-two">
            <div>
              <h3>按主题计数</h3>
              <ul>{topic_counts_html}</ul>
            </div>
            <div>
              <h3>按文件结果</h3>
              <ul>{topic_item_html}</ul>
            </div>
          </div>
        </section>
        <section class="card right-card">
          <h2>笔记预览</h2>
          <pre>{html.escape(final_doc_preview or '（暂无可预览内容）')}</pre>
        </section>
        """
        if lab_mode:
            result_summary_html += f"""
            <section class="card right-card">
              <details>
                <summary>查看完整处理摘要（调试）</summary>
                {_render_result_summary(result)}
              </details>
            </section>
            """
    else:
        result_summary_html = f"""
        <section class="card right-card">
          <h2>结果摘要</h2>
          <p class="empty">尚未开始运行。完成后会在这里显示结果摘要与导出入口。</p>
          <div class="result-actions">
            <span class="disabled-action">打开结果文件（未生成）</span>
            <a class="secondary-link" href="{html.escape(output_browser_link)}">打开输出目录</a>
          </div>
        </section>
        """

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>KnowledgeHarness · 笔记整理</title>
  <style>
    :root {{
      --bg: #f5f7fb;
      --surface: #ffffff;
      --surface-soft: #f8fafc;
      --border: #e5e7eb;
      --text: #111827;
      --text-muted: #6b7280;
      --primary: #111827;
      --primary-ink: #ffffff;
      --ok: #047857;
      --warn: #b45309;
      --danger: #b91c1c;
      --radius: 10px;
      --radius-sm: 8px;
      --shadow: 0 1px 2px rgba(16,24,40,.04), 0 1px 3px rgba(16,24,40,.08);
    }}

    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; padding: 0; }}
    body {{
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", Helvetica, Arial,
                   "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
      font-size: 14px;
      line-height: 1.55;
      padding: 22px 18px 42px;
    }}
    .wrap {{ max-width: 1280px; margin: 0 auto; }}

    .app-header {{ margin-bottom: 14px; }}
    .app-header h1 {{ margin: 0; font-size: 24px; font-weight: 650; display: flex; align-items: center; gap: 10px; }}
    .subtitle {{ margin: 6px 0 0; color: var(--text-muted); font-size: 13px; }}

    .global-msg {{ margin-bottom: 12px; }}
    .ok, .error, .status {{ padding: 10px 12px; border-radius: var(--radius-sm); margin-bottom: 8px; font-size: 13px; }}
    .ok {{ background: #ecfdf5; color: var(--ok); border: 1px solid #a7f3d0; }}
    .error {{ background: #fef2f2; color: #991b1b; border: 1px solid #fecaca; }}
    .status {{ background: #fff7ed; color: var(--warn); border: 1px solid #fde68a; }}

    .layout {{ display: grid; grid-template-columns: minmax(380px, 1.05fr) minmax(420px, 1fr); gap: 16px; align-items: start; }}
    .left-col, .right-col {{ min-width: 0; }}

    .card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 16px 16px;
      margin-bottom: 12px;
    }}
    .left-card h2, .right-card h2 {{ margin: 0 0 10px 0; font-size: 15px; }}
    h3 {{ margin: 0 0 8px 0; font-size: 13px; color: var(--text-muted); font-weight: 600; }}

    .card-head {{ display: flex; align-items: center; justify-content: space-between; gap: 8px; }}
    .pool-count {{ display: inline-flex; align-items: center; justify-content: center; min-width: 28px; height: 22px;
      border: 1px solid var(--border); border-radius: 999px; font-size: 12px; color: var(--text-muted); }}

    .support-tags {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }}
    .tag {{ font-size: 12px; color: var(--text-muted); border: 1px solid var(--border); border-radius: 999px; padding: 2px 8px; background: var(--surface-soft); }}

    .hint {{ margin: 6px 0 0; color: var(--text-muted); font-size: 12px; }}
    .empty {{ color: var(--text-muted); margin: 0; }}

    label {{ display: block; margin-bottom: 6px; font-weight: 520; font-size: 13px; }}
    input[type=text], input[type=number], select {{
      width: 100%;
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      background: #fff;
      padding: 8px 10px;
      font: inherit;
      color: var(--text);
    }}
    input:focus, select:focus {{ outline: none; border-color: #374151; box-shadow: 0 0 0 3px rgba(55,65,81,.1); }}
    .row {{ margin-bottom: 12px; }}
    .inline-checks {{ display: flex; flex-wrap: wrap; gap: 14px; }}
    .inline-checks label {{ margin: 0; font-weight: 420; }}

    .file-pickers {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }}
    .hidden-file {{ position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }}

    .primary-btn, .secondary-link, .secondary-btn, .tertiary {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: var(--radius-sm);
      padding: 8px 14px;
      text-decoration: none;
      font: inherit;
      cursor: pointer;
      border: 1px solid transparent;
      transition: all .15s ease;
      white-space: nowrap;
    }}
    .primary-btn {{
      width: 100%;
      background: var(--primary);
      color: var(--primary-ink);
      font-weight: 620;
      height: 40px;
    }}
    .primary-btn:hover {{ background: #000; }}
    .primary-btn[disabled] {{ background: #9ca3af; cursor: progress; }}

    .secondary-btn, .secondary-link {{
      background: #fff;
      color: var(--text);
      border-color: var(--border);
      font-weight: 520;
    }}
    .secondary-btn:hover, .secondary-link:hover {{ background: var(--surface-soft); }}

    .tertiary {{ background: transparent; border-color: var(--border); color: var(--text-muted); font-size: 12px; padding: 7px 10px; }}
    .tertiary:hover {{ background: var(--surface-soft); color: var(--text); }}
    .tertiary.danger {{ color: var(--danger); border-color: #fecaca; }}
    .tertiary.danger:hover {{ background: #fff1f2; }}
    .disabled-action {{ display: inline-flex; align-items: center; border: 1px dashed var(--border); color: var(--text-muted); border-radius: var(--radius-sm); padding: 8px 12px; font-size: 13px; }}

    .actions-row {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }}

    .pool-list {{ list-style: none; margin: 8px 0 0; padding: 0; }}
    .pool-row {{ display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 0; border-bottom: 1px solid #f1f5f9; }}
    .pool-row:last-child {{ border-bottom: 0; }}
    .pool-pick {{ display: flex; align-items: center; gap: 8px; min-width: 0; flex: 1 1 auto; margin: 0; }}
    .pool-pick input[type=checkbox] {{ margin: 0; }}
    .pool-name {{ max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 520; }}
    .pool-meta {{ color: var(--text-muted); font-size: 12px; white-space: nowrap; }}
    .file-status {{ color: var(--text-muted); font-size: 11px; border: 1px solid var(--border); border-radius: 999px; padding: 1px 8px; }}
    .file-status.selected {{ color: var(--ok); border-color: #a7f3d0; background: #ecfdf5; }}
    .pool-remove {{ margin: 0; }}
    .link-btn {{ border: 0; background: transparent; color: var(--danger); text-decoration: underline; cursor: pointer; font-size: 12px; }}
    .type-pill {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 11px; border: 1px solid var(--border); border-radius: 4px; background: #f8fafc; color: var(--text-muted); padding: 1px 6px; }}
    .type-pill.type-img {{ background: #fffbeb; border-color: #fde68a; color: var(--warn); }}
    .pool-warn {{ margin: 8px 0 0; color: var(--warn); font-size: 12px; }}

    .stage-head {{ display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }}
    .stage-title {{ font-size: 18px; font-weight: 620; margin: 0; }}
    .stage-desc {{ margin: 2px 0 0; color: var(--text-muted); }}

    .stats-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 8px; margin-top: 10px; }}
    .stat {{ border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface-soft); padding: 8px 10px; }}
    .stat .k {{ display: block; color: var(--text-muted); font-size: 12px; }}
    .stat .v {{ display: block; font-weight: 650; font-size: 18px; line-height: 1.2; margin-top: 2px; }}

    .steps {{ list-style: none; padding: 0; margin: 10px 0 0; display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }}
    .step {{ font-size: 12px; border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 6px 8px; display: flex; align-items: center; gap: 6px; color: var(--text-muted); }}
    .step .dot {{ width: 7px; height: 7px; border-radius: 50%; background: #d1d5db; }}
    .step.done {{ color: var(--ok); border-color: #a7f3d0; background: #ecfdf5; }}
    .step.done .dot {{ background: var(--ok); }}
    .step.error {{ color: var(--danger); border-color: #fecaca; background: #fef2f2; }}
    .step.error .dot {{ background: var(--danger); }}

    .log-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
    .log-grid ul {{ margin: 0; padding-left: 18px; }}
    .log-grid li {{ font-size: 12px; margin: 2px 0; }}

    .kv-list {{ list-style: none; margin: 0 0 10px; padding: 0; }}
    .kv-list li {{ padding: 4px 0; border-bottom: 1px solid #f1f5f9; font-size: 13px; }}
    .kv-list li:last-child {{ border-bottom: 0; }}

    .result-actions {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }}
    .download-row {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .download-btn {{ display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 8px 12px; text-decoration: none; color: var(--text); background: #fff; }}
    .download-btn:hover {{ background: var(--surface-soft); }}
    .download-btn .ext {{ font-size: 11px; color: var(--text-muted); background: #f3f4f6; border-radius: 4px; padding: 1px 5px; }}
    .download-missing {{ display: inline-flex; border: 1px dashed var(--border); border-radius: var(--radius-sm); color: var(--text-muted); padding: 8px 12px; font-size: 12px; }}

    .grid-two {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
    details {{ border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 8px 10px; background: var(--surface-soft); }}
    details > summary {{ cursor: pointer; font-weight: 520; font-size: 13px; }}

    pre {{
      margin: 0;
      border: 1px solid #eef2f7;
      background: #f8fafc;
      border-radius: var(--radius-sm);
      padding: 10px;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
      line-height: 1.5;
      max-height: 380px;
      overflow: auto;
    }}

    .mode-badge {{ display: inline-flex; border: 1px solid #fde68a; background: #fffbeb; color: var(--warn); border-radius: 999px; padding: 2px 8px; font-size: 11px; font-weight: 520; }}
    .api-chip {{ display: inline-flex; align-items: center; gap: 6px; text-decoration: none; border: 1px solid var(--border); border-radius: 999px; padding: 2px 10px; font-size: 11px; color: var(--text); background: #fff; }}
    .api-chip:hover {{ background: var(--surface-soft); }}
    .api-chip-dot {{ width: 6px; height: 6px; border-radius: 50%; background: #9ca3af; }}
    .api-chip.on {{ color: var(--ok); border-color: #a7f3d0; background: #ecfdf5; }}
    .api-chip.on .api-chip-dot {{ background: var(--ok); }}

    @media (max-width: 1080px) {{
      .layout {{ grid-template-columns: 1fr; }}
      .stats-grid, .steps, .grid-two, .log-grid {{ grid-template-columns: 1fr; }}
      .pool-meta {{ display: none; }}
      .pool-name {{ max-width: 170px; }}
    }}
  </style>
  <script>
    document.addEventListener("DOMContentLoaded", function () {{
      var form = document.getElementById("runForm");
      var pickFile = document.getElementById("upload_files");
      var pickFolder = document.getElementById("upload_folder");
      var pickedHint = document.getElementById("pickedHint");
      var resetPickedBtn = document.getElementById("resetPickedBtn");

      function updatePickedHint() {{
        var total = 0;
        if (pickFile && pickFile.files) total += pickFile.files.length;
        if (pickFolder && pickFolder.files) total += pickFolder.files.length;
        if (!pickedHint) return;
        pickedHint.textContent = total > 0 ? ("已选择 " + total + " 个待上传文件") : "尚未选择本次新上传文件";
      }}

      if (pickFile) pickFile.addEventListener("change", updatePickedHint);
      if (pickFolder) pickFolder.addEventListener("change", updatePickedHint);
      if (resetPickedBtn) {{
        resetPickedBtn.addEventListener("click", function () {{
          if (pickFile) pickFile.value = "";
          if (pickFolder) pickFolder.value = "";
          updatePickedHint();
        }});
      }}
      updatePickedHint();

      if (!form) return;
      form.addEventListener("submit", function () {{
        var btn = document.getElementById("submitBtn");
        if (btn) {{
          btn.disabled = true;
          btn.textContent = "处理中，请稍候…";
        }}
        var slot = document.getElementById("runtimeStatusSlot");
        if (slot) {{
          slot.innerHTML = '<div class="status">流水线执行中：读取 → 切分 → 主题粗分类 → 内容分类 → 总结 → 校验 → 导出…</div>';
        }}
      }});
    }});
  </script>
</head>
<body>
  <div class="wrap">
    <header class="app-header">
      <h1>KnowledgeHarness {mode_badge} {_api_status_chip()}</h1>
      <p class="subtitle">{html.escape(page_subtitle)}</p>
    </header>

    <div class="global-msg">
      {flash_html}
      {error_html}
      <div id="runtimeStatusSlot"></div>
    </div>

    <div class="layout">
      <main class="left-col">
        <section class="card left-card">
          <h2>输入与控制</h2>
          <p class="hint">先导入文件，再确认输出目录与选项，最后点击“{submit_button_label}”。</p>
          <div class="support-tags">
            <span class="tag">支持 .txt</span>
            <span class="tag">支持 .md</span>
            <span class="tag">支持 .pdf</span>
            <span class="tag">支持 .docx</span>
            <span class="tag">图片 OCR: .png/.jpg/.jpeg</span>
          </div>
        </section>

        <form id="runForm" method="post" action="/run" enctype="multipart/form-data">
          <input type="hidden" name="ui_mode" value="{'lab' if lab_mode else 'prod'}" />

          <section class="card left-card">
            <h2>文件导入</h2>
            <div class="file-pickers">
              <label class="secondary-btn" for="upload_files">选择文件</label>
              <label class="secondary-btn" for="upload_folder">选择文件夹</label>
              <button id="resetPickedBtn" type="button" class="tertiary">重置本次选择</button>
            </div>
            <input id="upload_files" class="hidden-file" type="file" name="upload_files" multiple />
            <input id="upload_folder" class="hidden-file" type="file" name="upload_files" webkitdirectory directory multiple />
            <p id="pickedHint" class="hint">尚未选择本次新上传文件</p>
            <p class="hint">单次上限：文件 ≤ {MAX_TOTAL_FILES_PER_RUN} 个；图片 ≤ {MAX_IMAGE_COUNT_PER_RUN} 张；单文件 ≤ {_format_size(MAX_FILE_SIZE_BYTES)}。</p>
          </section>

          <section class="card left-card">
            <h2>输出与运行选项</h2>
            <div class="row">
              <label for="output_dir">输出目录</label>
              <input id="output_dir" type="text" name="output_dir" value="{html.escape(output_dir)}" />
              <p class="hint">本次输出路径：<code>{html.escape(str(resolved_output_dir))}</code>{_download_support_hint(output_dir)}</p>
            </div>
            {controls_html}
          </section>

          <section class="card left-card">
            <h2>开始执行</h2>
            <button id="submitBtn" class="primary-btn" type="submit">{submit_button_label}</button>
            <div class="actions-row">
              <a class="secondary-link" href="/settings">API 设置</a>
              {lab_switch_html}
            </div>
          </section>
        </form>

        {pool_list_html}
      </main>

      <aside class="right-col">
        <section class="card right-card">
          <div class="stage-head">
            <div>
              <p class="stage-title">{html.escape(stage_title)}</p>
              <p class="stage-desc">{html.escape(stage_desc)}</p>
            </div>
          </div>

          <div class="stats-grid">
            <div class="stat"><span class="k">成功数</span><span class="v">{succeeded}</span></div>
            <div class="stat"><span class="k">失败数</span><span class="v">{failed}</span></div>
            <div class="stat"><span class="k">空文本数</span><span class="v">{empty_extracted}</span></div>
            <div class="stat"><span class="k">处理文件数</span><span class="v">{detected}</span></div>
          </div>

          <ul class="steps">{stage_steps_html}</ul>
        </section>

        <section class="card right-card">
          <h2>告警与日志摘要</h2>
          <div class="log-grid">
            <div>
              <h3>关键告警</h3>
              <ul>{warnings_html}</ul>
            </div>
            <div>
              <h3>Pipeline Notes</h3>
              <ul>{notes_html}</ul>
            </div>
          </div>
        </section>

        {result_summary_html}
      </aside>
    </div>
  </div>
</body>
</html>"""


def _render_output_browser_page(raw_dir: str, *, lab_mode: bool = False) -> str:
    resolved = _resolve_output_dir(raw_dir or "outputs")
    back_href = "/lab" if lab_mode else "/"

    rows: List[str] = []
    warning = ""
    if not resolved.exists():
        warning = f"输出目录不存在：{resolved}"
    elif not resolved.is_dir():
        warning = f"输出路径不是目录：{resolved}"
    else:
        entries = sorted(
            list(resolved.iterdir()),
            key=lambda p: (0 if p.is_file() else 1, -p.stat().st_mtime, p.name.lower()),
        )
        for p in entries[:300]:
            try:
                stat = p.stat()
                mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime))
                size_text = "-" if p.is_dir() else _format_size(int(stat.st_size))
            except OSError:
                mtime = "-"
                size_text = "-"
            if p.is_dir():
                rows.append(
                    "<tr>"
                    f"<td>{html.escape(p.name)}</td>"
                    "<td>目录</td>"
                    f"<td>{html.escape(size_text)}</td>"
                    f"<td>{html.escape(mtime)}</td>"
                    "<td>（目录）</td>"
                    "</tr>"
                )
                continue

            download_name = ""
            try:
                rp = p.resolve()
                rp.relative_to(OUTPUT_WHITELIST_ROOT)
                if rp.parent == OUTPUT_WHITELIST_ROOT:
                    download_name = rp.name
            except Exception:
                download_name = ""

            action = (
                f'<a href="/download?name={html.escape(download_name)}" download>下载</a>'
                if download_name
                else '<span style="color:#6b7280">不可下载（路径不在 outputs 根目录）</span>'
            )
            rows.append(
                "<tr>"
                f"<td>{html.escape(p.name)}</td>"
                "<td>文件</td>"
                f"<td>{html.escape(size_text)}</td>"
                f"<td>{html.escape(mtime)}</td>"
                f"<td>{action}</td>"
                "</tr>"
            )

    table_html = (
        "<table><thead><tr><th>名称</th><th>类型</th><th>大小</th><th>修改时间</th><th>操作</th></tr></thead>"
        f"<tbody>{''.join(rows) if rows else '<tr><td colspan=5>（无文件）</td></tr>'}</tbody></table>"
    )
    warning_html = (
        f'<p class="warn">{html.escape(warning)}</p>'
        if warning
        else ""
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>输出目录 · KnowledgeHarness</title>
  <style>
    body {{
      margin: 0;
      padding: 24px;
      background: #f8fafc;
      color: #111827;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", Helvetica, Arial,
                   "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 14px;
    }}
    .wrap {{ max-width: 980px; margin: 0 auto; }}
    .card {{
      background: #fff;
      border: 1px solid #e5e7eb;
      border-radius: 10px;
      box-shadow: 0 1px 2px rgba(16,24,40,.04), 0 1px 3px rgba(16,24,40,.08);
      padding: 16px;
    }}
    h1 {{ margin: 0 0 8px 0; font-size: 22px; }}
    p {{ margin: 6px 0; }}
    .hint {{ color: #6b7280; font-size: 13px; }}
    .warn {{ color: #b45309; background: #fff7ed; border: 1px solid #fde68a; border-radius: 8px; padding: 8px 10px; }}
    .actions {{ margin-bottom: 12px; display: flex; gap: 8px; flex-wrap: wrap; }}
    .btn {{
      display: inline-flex; align-items: center; justify-content: center;
      border: 1px solid #d1d5db; border-radius: 8px;
      padding: 7px 12px; text-decoration: none; color: #111827; background: #fff;
      font-size: 13px;
    }}
    .btn:hover {{ background: #f3f4f6; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid #eef2f7; padding: 8px; text-align: left; }}
    th {{ color: #6b7280; font-weight: 600; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>输出目录</h1>
      <p class="hint">当前目录：<code>{html.escape(str(resolved))}</code></p>
      <p class="hint">说明：浏览器“下载”仅支持 <code>outputs/</code> 根目录下的文件。</p>
      {warning_html}
      <div class="actions">
        <a class="btn" href="{back_href}">返回主界面</a>
      </div>
      {table_html}
    </div>
  </div>
</body>
</html>"""


def _render_settings_page(
    error: str = "",
    success: str = "",
    selected_profile_name: str = "",
) -> str:
    """Render the API harness settings console."""
    envs = _read_env_pairs()
    profiles_payload = _load_api_profiles()
    names = _profile_names(profiles_payload)
    active_profile = (
        os.getenv(ACTIVE_PROFILE_ENV_KEY, "").strip()
        or str(profiles_payload.get("active_profile", "")).strip()
    )
    if active_profile not in names:
        active_profile = ""
    selected_profile_name = _sanitize_profile_name(selected_profile_name) or active_profile
    if selected_profile_name not in names:
        selected_profile_name = ""
    selected_profile = _profile_by_name(profiles_payload, selected_profile_name) if selected_profile_name else None

    def _status(key: str) -> str:
        current = envs.get(key) or os.getenv(key) or ""
        return _mask_value(current)

    def _render_field(key: str, kind: str, label: str) -> str:
        field_type = "password" if kind == "password" else "text"
        auto = "new-password" if kind == "password" else "off"
        placeholder = "留空保持当前值；点击右侧 × 可清空"
        toggle = ""
        if kind == "password":
            toggle = (
                f'<button type="button" class="icon-btn" title="显示/隐藏" '
                f'data-toggle-visibility="{key}">👁</button>'
            )
        return f"""
        <div class="form-row">
          <label for="{key}">{html.escape(label)}</label>
          <div class="field-meta">
            <span class="status-chip">{html.escape(_status(key))}</span>
            <span class="env-name">{html.escape(key)}</span>
          </div>
          <div class="input-wrap">
            <input id="{key}" type="{field_type}" name="{key}" value=""
                   placeholder="{placeholder}" autocomplete="{auto}" />
            <input type="hidden" name="{key}__clear" value="" data-clear-target="{key}" />
            <button type="button" class="icon-btn" title="清空字段" data-clear-field="{key}">×</button>
            {toggle}
            <button type="button" class="icon-btn" title="复制当前输入" data-copy-field="{key}">复制</button>
          </div>
        </div>
        """

    unified_section = "".join(
        _render_field(
            k,
            "password" if k.endswith("_KEY") else "url",
            "统一 API 地址" if k.endswith("_URL") else "统一 API 密钥",
        )
        for k in API_ENV_KEYS
    )
    module_section = "".join(_render_field(k, kind, label) for k, kind, label in MODULE_OVERRIDE_KEYS)
    options = "".join(
        f'<option value="{html.escape(n)}" {_selected(selected_profile_name, n)}>{html.escape(n)}</option>'
        for n in names
    ) or '<option value="">（暂无可选档案）</option>'

    def _detail_value(key: str, value: str) -> str:
        raw = (value or "").strip()
        if key.endswith("_KEY"):
            return html.escape(_mask_value(raw))
        if not raw:
            return "（未配置）"
        return html.escape(raw)

    profile_detail_rows = ""
    selected_profile_configured = 0
    if selected_profile is not None:
        rows = []
        for k in PROFILE_ENV_KEYS:
            value = str(selected_profile.get(k, "") or "")
            if value.strip():
                selected_profile_configured += 1
            rows.append(
                "<tr>"
                f"<td><code>{html.escape(k)}</code></td>"
                f"<td>{_detail_value(k, value)}</td>"
                "</tr>"
            )
        profile_detail_rows = "".join(rows)
    else:
        profile_detail_rows = '<tr><td colspan="2">当前未选中档案，请先在上方选择。</td></tr>'

    profiles_list_html = "".join(
        "<tr>"
        f"<td>{html.escape(n)}</td>"
        f"<td>{'已激活' if n == active_profile else '—'}</td>"
        "</tr>"
        for n in names
    )
    if not profiles_list_html:
        profiles_list_html = '<tr><td colspan="2">（暂无档案）</td></tr>'

    unified_url = (envs.get("KNOWLEDGEHARNESS_API_URL") or os.getenv("KNOWLEDGEHARNESS_API_URL", "")).strip()
    topic_url = (envs.get("TOPIC_CLASSIFIER_API_URL") or os.getenv("TOPIC_CLASSIFIER_API_URL", "")).strip()
    image_url = (envs.get("IMAGE_OCR_API_URL") or os.getenv("IMAGE_OCR_API_URL", "")).strip()
    web_url = (envs.get("WEB_ENRICHMENT_API_URL") or os.getenv("WEB_ENRICHMENT_API_URL", "")).strip()
    configured_modules = (
        int(bool(topic_url or unified_url))
        + int(bool(image_url or unified_url))
        + int(bool(web_url or unified_url))
    )
    advanced_configured = sum(
        1 for k, _, _ in MODULE_OVERRIDE_KEYS if (envs.get(k) or os.getenv(k, "")).strip()
    )
    status_label = "Ready" if configured_modules == 3 else ("Partial" if configured_modules else "Incomplete")
    status_badge = (
        "status-ready" if status_label == "Ready"
        else ("status-partial" if status_label == "Partial" else "status-incomplete")
    )

    toast_html = ""
    if success:
        toast_html = f'<div class="toast toast-ok" role="status">{html.escape(success)}</div>'
    elif error:
        toast_html = f'<div class="toast toast-error" role="alert">{html.escape(error)}</div>'

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
      --ok: #047857; --danger: #b91c1c; --warn: #b45309;
      --radius: 10px; --radius-sm: 6px;
      --shadow-1: 0 1px 2px rgba(16,24,40,.04), 0 1px 3px rgba(16,24,40,.06);
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; padding: 0; }}
    body {{
      padding: 28px 22px 64px; background: var(--bg); color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                   "Helvetica Neue", Helvetica, Arial,
                   "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei",
                   "Noto Sans CJK SC", sans-serif;
      font-size: 14px; line-height: 1.5;
      -webkit-font-smoothing: antialiased;
    }}
    .wrap {{ max-width: 1160px; margin: 0 auto; }}
    .app-header h1 {{ margin: 0; font-size: 22px; font-weight: 600; letter-spacing: -0.01em; }}
    .app-header .subtitle {{ margin: 6px 0 0 0; color: var(--text-muted); font-size: 13px; }}
    .app-header {{ margin-bottom: 14px; }}
    .status-bar {{
      display: flex; flex-wrap: wrap; gap: 12px 16px; align-items: center;
      border: 1px solid var(--border); border-radius: var(--radius-sm);
      background: var(--surface); padding: 10px 12px; margin-bottom: 14px;
      box-shadow: var(--shadow-1);
    }}
    .status-item {{ color: var(--text-muted); font-size: 12.5px; }}
    .status-item b {{ color: var(--text); font-weight: 600; }}
    .status-ready {{ color: var(--ok) !important; }}
    .status-partial {{ color: var(--warn) !important; }}
    .status-incomplete {{ color: var(--danger) !important; }}
    .layout {{
      display: grid; gap: 14px;
      grid-template-columns: minmax(0, 1.2fr) minmax(0, 0.8fr);
      align-items: start;
    }}
    .card {{
      background: var(--surface); border: 1px solid var(--border);
      border-radius: var(--radius); padding: 18px; box-shadow: var(--shadow-1);
    }}
    .card h2 {{ margin: 0 0 12px 0; font-size: 15px; font-weight: 600; }}
    .section-note {{ margin: -4px 0 14px 0; color: var(--text-muted); font-size: 12.5px; }}
    .form-row {{ margin-bottom: 14px; }}
    label {{ display: block; margin-bottom: 6px; font-weight: 500; font-size: 13px; }}
    .field-meta {{ display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }}
    .status-chip {{
      display: inline-block; padding: 1px 8px; border-radius: 999px;
      background: var(--accent-soft); color: var(--text-muted); font-size: 11.5px;
    }}
    .env-name {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      color: var(--text-muted); font-size: 11.5px;
    }}
    .input-wrap {{
      display: grid; gap: 8px; align-items: center;
      grid-template-columns: minmax(0, 1fr) auto auto auto;
    }}
    input[type=text], input[type=password], select {{
      width: 100%; padding: 8px 10px;
      border: 1px solid var(--border); border-radius: var(--radius-sm);
      background: var(--surface); font: inherit;
      transition: border-color .15s, box-shadow .15s;
    }}
    input:focus, select:focus {{
      outline: none; border-color: var(--text);
      box-shadow: 0 0 0 3px rgba(17,24,39,.08);
    }}
    .icon-btn {{
      border: 1px solid var(--border); background: var(--surface);
      color: var(--text-muted); border-radius: var(--radius-sm);
      height: 34px; min-width: 34px; padding: 0 8px;
      font-size: 12px; cursor: pointer;
    }}
    .icon-btn:hover {{ background: var(--accent-soft); color: var(--text); }}
    .btn-row {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
    button {{
      background: var(--accent); color: var(--accent-ink);
      border: 0; border-radius: var(--radius-sm);
      padding: 8px 14px; font: inherit; font-weight: 500; cursor: pointer;
    }}
    button:hover {{ background: #000; }}
    .ghost-btn {{
      background: var(--surface); color: var(--text);
      border: 1px solid var(--border);
    }}
    .ghost-btn:hover {{ background: var(--accent-soft); }}
    .danger-btn {{
      background: #b91c1c; color: #fff; border: 0;
    }}
    .danger-btn:hover {{ background: #991b1b; }}
    .back {{
      display: inline-block; text-decoration: none;
      background: var(--surface); color: var(--text);
      border: 1px solid var(--border); border-radius: var(--radius-sm);
      padding: 8px 14px; font-weight: 500;
    }}
    .back:hover {{ background: var(--accent-soft); }}
    details {{
      border: 1px solid var(--border);
      border-radius: var(--radius-sm); padding: 10px 12px;
      background: var(--surface-2);
    }}
    details > summary {{
      cursor: pointer; font-weight: 500; color: var(--text);
      list-style: none; font-size: 13px;
    }}
    details > summary::before {{
      content: "▸"; display: inline-block; margin-right: 6px; color: var(--text-muted);
      transition: transform .15s;
    }}
    details[open] > summary::before {{ transform: rotate(90deg); }}
    .mini-table {{
      width: 100%; border-collapse: collapse; margin-top: 10px;
      border: 1px solid var(--border); border-radius: var(--radius-sm); overflow: hidden;
    }}
    .mini-table th, .mini-table td {{
      border-bottom: 1px solid var(--border-soft); padding: 8px 10px;
      text-align: left; font-size: 12.5px;
      vertical-align: top;
    }}
    .mini-table th {{ background: var(--surface-2); color: var(--text-muted); font-weight: 600; }}
    .mini-table tr:last-child td {{ border-bottom: 0; }}
    code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px; background: var(--accent-soft);
      padding: 1px 5px; border-radius: 4px;
    }}
    .empty-tip {{
      border: 1px dashed var(--border); border-radius: var(--radius-sm);
      background: var(--surface-2); color: var(--text-muted);
      padding: 10px 12px; font-size: 12.5px;
    }}
    .toast {{
      position: fixed; right: 16px; top: 16px; z-index: 50;
      padding: 10px 12px; border-radius: var(--radius-sm); font-size: 12.5px;
      border: 1px solid transparent; box-shadow: var(--shadow-1);
      max-width: 520px;
    }}
    .toast-ok {{ background: #ecfdf5; color: var(--ok); border-color: #a7f3d0; }}
    .toast-error {{ background: #fef2f2; color: #991b1b; border-color: #fecaca; }}
    .profile-card {{ margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--border-soft); }}
    .profile-badges {{
      display: flex; gap: 8px; flex-wrap: wrap; margin: 4px 0 10px;
      color: var(--text-muted); font-size: 12px;
    }}
    .profile-badge {{
      background: var(--surface-2); border: 1px solid var(--border);
      border-radius: 999px; padding: 2px 10px;
    }}
    .danger-area {{ margin-top: 10px; }}
    @media (max-width: 980px) {{
      .layout {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 720px) {{
      body {{ padding: 20px 12px 42px; }}
      .wrap {{ max-width: 100%; }}
      .input-wrap {{ grid-template-columns: minmax(0, 1fr) auto auto; }}
      .input-wrap .icon-btn[data-copy-field] {{ grid-column: 2 / span 2; }}
    }}
  </style>
</head>
<body>
  {toast_html}
  <div class="wrap">
    <header class="app-header">
      <h1>API 配置控制台</h1>
      <p class="subtitle">状态 > 配置 > 应用 > 治理。仅处理 API 环境与档案，不影响主流水线结构。</p>
    </header>

    <section class="status-bar">
      <div class="status-item">当前激活档案：<b>{html.escape(active_profile or "未指定")}</b></div>
      <div class="status-item">已保存档案：<b>{len(names)}</b></div>
      <div class="status-item">模块就绪：<b>{configured_modules}/3</b></div>
      <div class="status-item">最近连通性测试：<b>未执行</b></div>
      <div class="status-item">环境状态：<b class="{status_badge}">{status_label}</b></div>
    </section>

    <div class="layout">
      <section class="card">
        <h2>基础配置</h2>
        <p class="section-note">优先填写统一地址和密钥。留空表示保持不变；点击字段右侧 × 会在保存时清空该字段。</p>
        <form method="post" action="/settings" autocomplete="off">
          <input type="hidden" name="action" value="save_env" />
          {unified_section}

          <details>
            <summary>高级配置（按模块覆盖，已覆盖 {advanced_configured} 项）</summary>
            <p class="section-note">模块字段为空时自动回退到统一 API 配置。</p>
            {module_section}
          </details>
          <div class="btn-row" style="margin-top: 14px;">
            <button type="submit">保存当前配置</button>
            <a class="back" href="/">返回主页</a>
          </div>
        </form>
      </section>

      <section class="card">
        <h2>API 档案</h2>
        <p class="section-note">保存、切换和治理多套 API 配置。</p>

        <form method="post" action="/settings" autocomplete="off">
          <input type="hidden" name="action" value="select_profile" />
          <div class="form-row">
            <label for="selected_profile_name">当前档案</label>
            <select id="selected_profile_name" name="selected_profile_name" onchange="this.form.submit()">
              {options}
            </select>
          </div>
          <div class="btn-row">
            <button type="submit" class="ghost-btn">加载档案</button>
          </div>
        </form>

        <table class="mini-table">
          <thead><tr><th>档案名</th><th>状态</th></tr></thead>
          <tbody>{profiles_list_html}</tbody>
        </table>

        <form method="post" action="/settings" autocomplete="off" class="profile-card">
          <input type="hidden" name="action" value="save_profile_current" />
          <div class="form-row">
            <label for="profile_name">新建/覆盖档案名</label>
            <input id="profile_name" type="text" name="profile_name" placeholder="例如：主线路 API / 备用 API" />
          </div>
          <div class="btn-row">
            <label style="display:inline-flex;align-items:center;gap:6px;font-weight:400;color:var(--text-muted);">
              <input type="checkbox" name="set_active_on_save" checked />
              <span>保存后设为默认</span>
            </label>
            <button type="submit">保存当前环境为档案</button>
          </div>
        </form>

        <div class="profile-card">
          <h2 style="margin-bottom: 6px;">选中档案详情</h2>
          <div class="profile-badges">
            <span class="profile-badge">档案：{html.escape(selected_profile_name or "未选择")}</span>
            <span class="profile-badge">已配置字段：{selected_profile_configured}/{len(PROFILE_ENV_KEYS)}</span>
            <span class="profile-badge">默认：{"是" if selected_profile_name and selected_profile_name == active_profile else "否"}</span>
          </div>
          {"<div class='empty-tip'>请先选择一个档案后再执行应用或治理操作。</div>" if not selected_profile_name else ""}
          <table class="mini-table">
            <thead><tr><th>字段</th><th>值</th></tr></thead>
            <tbody>{profile_detail_rows}</tbody>
          </table>

          <form method="post" action="/settings" autocomplete="off" style="margin-top: 10px;">
            <input type="hidden" name="selected_profile_name" value="{html.escape(selected_profile_name)}" />
            <div class="btn-row">
              <button type="submit" name="action" value="apply_profile" {"disabled" if not selected_profile_name else ""}>应用到当前环境</button>
              <label style="display:inline-flex;align-items:center;gap:6px;font-weight:400;color:var(--text-muted);">
                <input type="checkbox" name="apply_set_default" />
                <span>同时设为默认</span>
              </label>
            </div>
          </form>

          <details class="danger-area">
            <summary style="color:#b91c1c;">危险操作（需确认）</summary>
            <p class="section-note">以下操作不可撤销。请确认当前选中档案正确。</p>
            <form method="post" action="/settings" autocomplete="off">
              <input type="hidden" name="selected_profile_name" value="{html.escape(selected_profile_name)}" />
              <div class="btn-row">
                <button type="submit" name="action" value="overwrite_profile_from_env" class="danger-btn" {"disabled" if not selected_profile_name else ""}>用当前环境覆盖档案</button>
                <button type="submit" name="action" value="delete_profile" class="danger-btn" {"disabled" if not selected_profile_name else ""} onclick="return confirm('确认删除该档案？此操作不可撤销。');">删除档案</button>
                <button type="submit" name="action" value="clear_all_api_env" class="danger-btn" onclick="return confirm('确认清空当前全部 API 配置？');">清空当前环境 API</button>
              </div>
            </form>
          </details>
        </div>
      </section>
    </div>
  </div>
  <script>
    document.addEventListener("DOMContentLoaded", function () {{
      var toast = document.querySelector(".toast");
      if (toast) {{
        setTimeout(function () {{
          toast.style.opacity = "0";
          toast.style.transition = "opacity .2s";
          setTimeout(function () {{ toast.remove(); }}, 220);
        }}, 3200);
      }}

      var clearButtons = document.querySelectorAll("[data-clear-field]");
      clearButtons.forEach(function (btn) {{
        btn.addEventListener("click", function () {{
          var key = btn.getAttribute("data-clear-field");
          if (!key) return;
          var input = document.getElementById(key);
          var marker = document.querySelector('[data-clear-target="' + key + '"]');
          if (input) {{
            input.value = "";
            input.focus();
          }}
          if (marker) {{
            marker.value = "1";
          }}
        }});
      }});

      var trackedInputs = document.querySelectorAll(".input-wrap input[type=text], .input-wrap input[type=password]");
      trackedInputs.forEach(function (input) {{
        input.addEventListener("input", function () {{
          var key = input.getAttribute("id");
          if (!key) return;
          var marker = document.querySelector('[data-clear-target="' + key + '"]');
          if (marker && input.value.trim()) {{
            marker.value = "";
          }}
        }});
      }});

      var toggles = document.querySelectorAll("[data-toggle-visibility]");
      toggles.forEach(function (btn) {{
        btn.addEventListener("click", function () {{
          var key = btn.getAttribute("data-toggle-visibility");
          if (!key) return;
          var input = document.getElementById(key);
          if (!input) return;
          input.type = input.type === "password" ? "text" : "password";
        }});
      }});

      var copyButtons = document.querySelectorAll("[data-copy-field]");
      copyButtons.forEach(function (btn) {{
        btn.addEventListener("click", async function () {{
          var key = btn.getAttribute("data-copy-field");
          if (!key) return;
          var input = document.getElementById(key);
          if (!input) return;
          try {{
            await navigator.clipboard.writeText(input.value || "");
            btn.textContent = "已复制";
            setTimeout(function () {{ btn.textContent = "复制"; }}, 1200);
          }} catch (err) {{
            btn.textContent = "失败";
            setTimeout(function () {{ btn.textContent = "复制"; }}, 1200);
          }}
        }});
      }});
    }});
  </script>
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
        if route == "/lab" and LAB_ENABLED:
            self._write_html(_render_page(form={}, flash=flash, lab_mode=True))
            return
        if route == "/settings":
            self._write_html(_render_settings_page())
            return
        if route == "/download":
            self._serve_download(parsed.query)
            return
        if route == "/outputs":
            params = parse_qs(parsed.query, keep_blank_values=True)
            out_dir = (params.get("dir") or ["outputs"])[0]
            self._write_html(_render_output_browser_page(out_dir, lab_mode=False))
            return
        if route == "/lab/outputs" and LAB_ENABLED:
            params = parse_qs(parsed.query, keep_blank_values=True)
            out_dir = (params.get("dir") or ["outputs"])[0]
            self._write_html(_render_output_browser_page(out_dir, lab_mode=True))
            return
        self._write_html("<h1>未找到页面</h1>", status=404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/settings":
            length = int(self.headers.get("Content-Length", "0"))
            payload = self.rfile.read(length).decode("utf-8", errors="replace")
            form_raw = parse_qs(payload, keep_blank_values=True)
            try:
                action = (form_raw.get("action") or ["save_env"])[0].strip() or "save_env"
                selected_profile_name = _sanitize_profile_name(
                    (form_raw.get("selected_profile_name") or [""])[0]
                )

                def _apply_profile_env(profile_name: str, set_default: bool) -> tuple[int, int]:
                    data = _load_api_profiles()
                    profile = _profile_by_name(data, profile_name)
                    if profile is None:
                        raise ValueError(f"未找到档案：{profile_name}")
                    updates = _profile_updates(profile)
                    clears = {k for k, v in updates.items() if not v}
                    touched, cleared = _write_env_pairs(updates, clears=clears)
                    if set_default:
                        data["active_profile"] = profile_name
                        _save_api_profiles(data)
                        _write_env_pairs({ACTIVE_PROFILE_ENV_KEY: profile_name})
                    return len(touched), len(cleared)

                if action == "save_env":
                    updates = {
                        k: (form_raw.get(k) or [""])[0].strip()
                        for k in ALL_SETTINGS_KEYS
                    }
                    clears = {
                        k for k in ALL_SETTINGS_KEYS
                        if (form_raw.get(f"{k}__clear") or [""])[0]
                    }
                    touched, cleared = _write_env_pairs(updates, clears=clears)
                    parts: List[str] = []
                    if touched:
                        parts.append(f"更新了 {', '.join(touched)}")
                    if cleared:
                        parts.append(f"已清空 {', '.join(cleared)}")
                    msg = (
                        "保存成功：" + "；".join(parts)
                        if parts
                        else "未更改任何字段（所有字段留空且无清空请求视为保持原值）"
                    )
                elif action == "clear_all_api_env":
                    _, cleared = _write_env_pairs(
                        {},
                        clears=set(PROFILE_ENV_KEYS) | {ACTIVE_PROFILE_ENV_KEY},
                    )
                    msg = (
                        "已清空当前全部 API 环境配置"
                        if cleared else
                        "未检测到可清空的 API 环境配置"
                    )
                elif action == "save_profile_current":
                    profile_name = _sanitize_profile_name(
                        (form_raw.get("profile_name") or [""])[0]
                    )
                    if not profile_name:
                        raise ValueError("请先填写档案名称")
                    current_env = _read_env_pairs()
                    profile: Dict[str, str] = {"name": profile_name}
                    for k in PROFILE_ENV_KEYS:
                        profile[k] = (current_env.get(k) or os.getenv(k, "")).strip()
                    if not any(profile.get(k) for k in PROFILE_ENV_KEYS):
                        raise ValueError("当前没有可保存的 API 配置，请先在上方填写并保存")

                    data = _load_api_profiles()
                    existing = _profile_by_name(data, profile_name)
                    if existing is None:
                        data["profiles"] = (data.get("profiles") or []) + [profile]
                    else:
                        for i, item in enumerate(data.get("profiles") or []):
                            if _sanitize_profile_name(str(item.get("name", ""))) == profile_name:
                                data["profiles"][i] = profile
                                break
                    set_active = bool((form_raw.get("set_active_on_save") or [""])[0])
                    if set_active:
                        data["active_profile"] = profile_name
                        _write_env_pairs({ACTIVE_PROFILE_ENV_KEY: profile_name})
                    _save_api_profiles(data)
                    msg = f"已保存 API 档案：{profile_name}" + ("（已设为默认）" if set_active else "")
                    selected_profile_name = profile_name
                elif action == "select_profile":
                    if not selected_profile_name:
                        raise ValueError("请先选择一个 API 档案")
                    data = _load_api_profiles()
                    if _profile_by_name(data, selected_profile_name) is None:
                        raise ValueError(f"未找到档案：{selected_profile_name}")
                    msg = f"已加载档案详情：{selected_profile_name}"
                elif action == "apply_profile":
                    if not selected_profile_name:
                        raise ValueError("请先选择一个 API 档案")
                    set_default = bool((form_raw.get("apply_set_default") or [""])[0])
                    t_count, c_count = _apply_profile_env(selected_profile_name, set_default=set_default)
                    msg = (
                        f"已应用 API 档案：{selected_profile_name}"
                        f"（更新 {t_count} 项，清空 {c_count} 项）"
                        + ("；并已设为默认" if set_default else "")
                    )
                elif action == "overwrite_profile_from_env":
                    if not selected_profile_name:
                        raise ValueError("请先选择要覆盖的档案")
                    data = _load_api_profiles()
                    profile = _profile_by_name(data, selected_profile_name)
                    if profile is None:
                        raise ValueError(f"未找到档案：{selected_profile_name}")
                    current_env = _read_env_pairs()
                    updated: Dict[str, str] = {"name": selected_profile_name}
                    for k in PROFILE_ENV_KEYS:
                        updated[k] = (current_env.get(k) or os.getenv(k, "")).strip()
                    for i, item in enumerate(data.get("profiles") or []):
                        if _sanitize_profile_name(str(item.get("name", ""))) == selected_profile_name:
                            data["profiles"][i] = updated
                            break
                    _save_api_profiles(data)
                    msg = f"已用当前环境覆盖档案：{selected_profile_name}"
                elif action == "delete_profile":
                    if not selected_profile_name:
                        raise ValueError("请先选择要删除的档案")
                    data = _load_api_profiles()
                    old_profiles = data.get("profiles") or []
                    new_profiles = [
                        p for p in old_profiles
                        if _sanitize_profile_name(str(p.get("name", ""))) != selected_profile_name
                    ]
                    if len(new_profiles) == len(old_profiles):
                        raise ValueError(f"未找到档案：{selected_profile_name}")
                    data["profiles"] = new_profiles
                    if _sanitize_profile_name(str(data.get("active_profile", ""))) == selected_profile_name:
                        data["active_profile"] = ""
                        _write_env_pairs({}, clears={ACTIVE_PROFILE_ENV_KEY})
                    _save_api_profiles(data)
                    msg = f"已删除 API 档案：{selected_profile_name}"
                    selected_profile_name = ""
                else:
                    raise ValueError(f"未知操作：{action}")

                self._write_html(_render_settings_page(success=msg, selected_profile_name=selected_profile_name))
            except Exception as exc:
                self._write_html(
                    _render_settings_page(error=f"保存失败: {exc}", selected_profile_name=selected_profile_name),
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
            target = "/lab" if mode == "lab" else "/"
            self._redirect(f"{target}?flash={quote(f'已清空文件池，移除 {removed} 个文件')}")
            return

        if self.path == "/uploads/remove":
            length = int(self.headers.get("Content-Length", "0"))
            payload = self.rfile.read(length).decode("utf-8", errors="replace")
            form_raw = parse_qs(payload, keep_blank_values=True)
            name = (form_raw.get("name") or [""])[0].strip()
            mode = (form_raw.get("ui_mode") or ["prod"])[0]
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
                "api_profile": _first("api_profile", ""),
                "topic_mode": _first("topic_mode", "auto"),
                "web_enrichment_mode": _first("web_enrichment_mode", "auto"),
                "enable_api_assist": "enable_api_assist" in fields,
                "enable_web_enrichment": "enable_web_enrichment" in fields,
                "export_docx": "export_docx" in fields,
                "keypoint_min_confidence": _first("keypoint_min_confidence", "0.0"),
                "keypoint_max_points": _first("keypoint_max_points", "12"),
                "validation_profile": _first("validation_profile", "strict"),
            }
        else:
            payload = self.rfile.read(total_len).decode("utf-8", errors="replace")
            form_raw = parse_qs(payload, keep_blank_values=True)
            existing_selected = list(form_raw.get("existing_files", []))
            form = {
                "ui_mode": (form_raw.get("ui_mode") or ["prod"])[0],
                "output_dir": (form_raw.get("output_dir") or ["outputs"])[0],
                "api_profile": (form_raw.get("api_profile") or [""])[0],
                "topic_mode": (form_raw.get("topic_mode") or ["auto"])[0],
                "web_enrichment_mode": (form_raw.get("web_enrichment_mode") or ["auto"])[0],
                "enable_api_assist": "enable_api_assist" in form_raw,
                "enable_web_enrichment": "enable_web_enrichment" in form_raw,
                "export_docx": "export_docx" in form_raw,
                "keypoint_min_confidence": (form_raw.get("keypoint_min_confidence") or ["0.0"])[0],
                "keypoint_max_points": (form_raw.get("keypoint_max_points") or ["12"])[0],
                "validation_profile": (form_raw.get("validation_profile") or ["strict"])[0],
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

            selected_profile_name = _sanitize_profile_name(str(form.get("api_profile", "") or ""))
            selected_profile: Dict[str, Any] | None = None
            if selected_profile_name:
                profile_payload = _load_api_profiles()
                selected_profile = _profile_by_name(profile_payload, selected_profile_name)
                if selected_profile is None:
                    raise ValueError(f"未找到 API 档案：{selected_profile_name}")

            def _run() -> Dict[str, Any]:
                run_kwargs, _meta = build_pipeline_run_kwargs(
                    config_path="config/pipeline_config.json",
                    topic_mode=str(form["topic_mode"] or "auto"),
                    web_enrichment_enabled=bool(form["enable_web_enrichment"]),
                    web_enrichment_mode=str(form["web_enrichment_mode"] or "auto"),
                    api_assist_enabled=bool(form["enable_api_assist"]),
                    keypoint_min_confidence=kp_min,
                    keypoint_max_points=kp_max,
                    validation_profile=str(form.get("validation_profile", "strict") or "strict"),
                    export_docx=bool(form["export_docx"]),
                    full_report=False,
                )
                return run_pipeline(
                    files,
                    output_dir=str(_resolve_output_dir(str(form.get("output_dir", "")))),
                    notifier=None,
                    **run_kwargs,
                )

            if selected_profile is not None:
                with _temporary_profile_env(selected_profile):
                    result = _run()
                notes = result.get("pipeline_notes") or []
                result["pipeline_notes"] = notes + [f"ui api profile used: {selected_profile_name}"]
            else:
                result = _run()
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
    load_local_env(".env")

    parser = argparse.ArgumentParser(description="KnowledgeHarness 简易本地界面")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", default=8765, type=int, help="监听端口")
    parser.add_argument(
        "--max-port-tries",
        default=30,
        type=int,
        help="端口占用时向后尝试的端口数量（含起始端口）",
    )
    args = parser.parse_args()

    server = create_server(args.host, args.port, max_port_tries=args.max_port_tries)
    resolved_host, resolved_port = server.server_address[:2]
    if int(resolved_port) != int(args.port):
        print(f"端口 {args.port} 已被占用，已自动切换到 {resolved_port}")
    print(f"简易界面已启动: http://{resolved_host}:{resolved_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def create_server(
    host: str,
    port: int,
    *,
    auto_fallback: bool = True,
    max_port_tries: int = 30,
) -> ThreadingHTTPServer:
    """Create the UI HTTP server.

    Exposed for launcher/wrapper modules that want to run the same UI server
    without invoking argparse in `main()`.

    Behavior:
    - If `auto_fallback=False`, bind exactly `port` and raise on conflict.
    - If `auto_fallback=True` (default), when `port` is occupied the function
      will try `port+1 ...` up to `max_port_tries` total attempts.
    """
    tries = max(1, int(max_port_tries))
    if not auto_fallback:
        return ThreadingHTTPServer((host, int(port)), _Handler)

    last_error: OSError | None = None
    start = int(port)
    for candidate in range(start, start + tries):
        try:
            return ThreadingHTTPServer((host, candidate), _Handler)
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE:
                raise
            last_error = exc
            continue

    raise OSError(
        errno.EADDRINUSE,
        f"no available port in range [{start}, {start + tries - 1}]",
    ) from last_error


if __name__ == "__main__":
    main()
