"""Web enrichment for KnowledgeHarness (switchable, failure-tolerant).

Design:
- User material remains primary; enrichment is supplementary only.
- Can run in local/url-extract mode without external API.
- Optional API mode must never crash the pipeline.
- Output schema is constrained to: title/url/purpose/relevance_reason
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List
from urllib import error, parse, request

_URL_RE = re.compile(r"https?://[^\s)\]}>\"']+")
DEFAULT_API_TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "api_payload_templates.json"
)


def _load_web_api_template() -> Dict[str, Any]:
    template_path = Path(
        os.getenv("WEB_ENRICHMENT_API_TEMPLATE", str(DEFAULT_API_TEMPLATE_PATH))
    )
    try:
        raw = json.loads(template_path.read_text(encoding="utf-8"))
        section = raw.get("web_enrichment", {}) if isinstance(raw, dict) else {}
        if not isinstance(section, dict):
            return {}
        return section
    except Exception:
        return {}


def _extract_json_object_from_text(content: str) -> Dict[str, Any]:
    text = (content or "").strip()
    if not text:
        raise ValueError("api returned empty text content")

    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", text).strip()
        text = re.sub(r"\n?```$", "", text).strip()

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        snippet = text[start : end + 1]
        try:
            data = json.loads(snippet)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    raise ValueError("api text content is not valid JSON object")


def _resolve_api_style(url: str, module_style_key: str) -> str:
    style = (
        os.getenv(module_style_key, "").strip().lower()
        or os.getenv("KNOWLEDGEHARNESS_API_STYLE", "").strip().lower()
        or "auto"
    )
    if style in {"custom", "openai_compatible"}:
        return style

    parsed = parse.urlparse(url)
    host = (parsed.netloc or "").lower()
    path = parsed.path or ""
    if "api.deepseek.com" in host or "api.openai.com" in host:
        return "openai_compatible"
    if path in {"", "/"}:
        return "openai_compatible"
    return "custom"


def _resolve_openai_endpoint(url: str) -> str:
    parsed = parse.urlparse(url)
    path = (parsed.path or "").rstrip("/")
    if path.endswith("/chat/completions"):
        final_path = path
    elif path.endswith("/v1"):
        final_path = f"{path}/chat/completions"
    elif path in {"", "/"}:
        final_path = "/v1/chat/completions"
    else:
        final_path = f"{path}/chat/completions"
    return parse.urlunparse(
        (parsed.scheme, parsed.netloc, final_path, parsed.params, parsed.query, parsed.fragment)
    )


def _normalize_url(url: str) -> str:
    return url.rstrip(".,;:!?)\]}")


def _build_local_resources(documents: List[Dict[str, Any]], max_items: int) -> List[Dict[str, str]]:
    seen = set()
    resources: List[Dict[str, str]] = []

    for doc in documents:
        source_name = doc.get("source_name") or "unknown"
        text = (doc.get("extracted_text") or doc.get("raw_text") or "")
        for raw_url in _URL_RE.findall(text):
            url = _normalize_url(raw_url)
            if not url or url in seen:
                continue
            seen.add(url)
            hostname = parse.urlparse(url).netloc or url
            resources.append(
                {
                    "title": f"User referenced link ({hostname})",
                    "url": url,
                    "purpose": "supplementary reading extracted from source material",
                    "relevance_reason": f"found directly in user source {source_name}",
                }
            )
            if len(resources) >= max_items:
                return resources

    return resources


def _call_enrichment_api(
    documents: List[Dict[str, Any]],
    timeout_sec: float,
    max_items: int,
) -> List[Dict[str, str]]:
    url = (
        os.getenv("WEB_ENRICHMENT_API_URL", "").strip()
        or os.getenv("KNOWLEDGEHARNESS_API_URL", "").strip()
    )
    if not url:
        raise RuntimeError("WEB_ENRICHMENT_API_URL is not configured")

    snippets = []
    for doc in documents[:8]:
        text = (doc.get("extracted_text") or "").strip()
        if text:
            snippets.append(
                {
                    "source_name": doc.get("source_name"),
                    "text": text[:1200],
                }
            )

    api_template = _load_web_api_template()
    output_contract = (
        api_template.get("output_contract")
        if isinstance(api_template.get("output_contract"), dict)
        else {
            "resources": [
                {
                    "title": "string",
                    "url": "string",
                    "purpose": "string",
                    "relevance_reason": "string",
                }
            ]
        }
    )
    payload = {
        "snippets": snippets,
        "max_items": max_items,
        "required_fields": ["title", "url", "purpose", "relevance_reason"],
        "system_prompt": str(api_template.get("system_prompt") or "").strip()
        or (
            "Return supplementary resources only with required fields: "
            "title/url/purpose/relevance_reason."
        ),
        "output_contract": output_contract,
        "rules": {
            "supplementary_only": True,
            "do_not_override_user_content": True,
        },
    }

    headers = {"Content-Type": "application/json"}
    api_key = (
        os.getenv("WEB_ENRICHMENT_API_KEY", "").strip()
        or os.getenv("KNOWLEDGEHARNESS_API_KEY", "").strip()
    )
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    style = _resolve_api_style(url, "WEB_ENRICHMENT_API_STYLE")
    request_url = url
    request_payload: Dict[str, Any]
    if style == "openai_compatible":
        request_url = _resolve_openai_endpoint(url)
        model = (
            os.getenv("WEB_ENRICHMENT_API_MODEL", "").strip()
            or os.getenv("KNOWLEDGEHARNESS_API_MODEL", "").strip()
            or "deepseek-chat"
        )
        request_payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": payload["system_prompt"]
                    + " 严格返回 JSON 对象，根字段必须是 resources。",
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "snippets": payload["snippets"],
                            "max_items": payload["max_items"],
                            "required_fields": payload["required_fields"],
                            "rules": payload["rules"],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
    else:
        request_payload = payload

    req = request.Request(
        url=request_url,
        method="POST",
        data=json.dumps(request_payload).encode("utf-8"),
        headers=headers,
    )

    with request.urlopen(req, timeout=timeout_sec) as resp:
        body = resp.read().decode("utf-8", errors="replace")

    data = json.loads(body)
    if style == "openai_compatible":
        choices = data.get("choices", []) if isinstance(data, dict) else []
        if not choices:
            raise ValueError("openai-compatible api returned empty choices")
        content = str(
            ((choices[0] or {}).get("message") or {}).get("content") or ""
        )
        data = _extract_json_object_from_text(content)

    items = data.get("resources", []) if isinstance(data, dict) else []
    if not isinstance(items, list):
        raise ValueError("web enrichment api returned invalid payload")

    cleaned: List[Dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        resource = {
            "title": str(item.get("title") or "").strip(),
            "url": str(item.get("url") or "").strip(),
            "purpose": str(item.get("purpose") or "").strip(),
            "relevance_reason": str(item.get("relevance_reason") or "").strip(),
        }
        if not resource["url"]:
            continue
        if not resource["title"]:
            resource["title"] = f"Reference ({resource['url']})"
        if not resource["purpose"]:
            resource["purpose"] = "supplementary reference"
        if not resource["relevance_reason"]:
            resource["relevance_reason"] = "api suggested"
        cleaned.append(resource)
        if len(cleaned) >= max_items:
            break

    return cleaned


def web_enrich(
    documents: List[Dict[str, Any]],
    enabled: bool = False,
    mode: str = "auto",
    timeout_sec: float = 6.0,
    max_items: int = 8,
    api_retries: int = 1,
) -> Dict[str, Any]:
    """Produce supplementary web resources.

    mode:
    - off: disabled
    - local: only extract URLs from user-provided documents
    - api: call external enrichment endpoint
    - auto: api if configured, otherwise local
    """
    if not enabled:
        return {
            "enabled": False,
            "mode_requested": mode,
            "mode_effective": "off",
            "resources": [],
            "warnings": [],
        }

    warnings: List[str] = []
    mode_norm = (mode or "auto").strip().lower()
    if mode_norm not in {"off", "local", "api", "auto"}:
        mode_norm = "auto"
        warnings.append("invalid web enrichment mode; fallback to auto")

    api_configured = bool(
        os.getenv("WEB_ENRICHMENT_API_URL", "").strip()
        or os.getenv("KNOWLEDGEHARNESS_API_URL", "").strip()
    )
    if mode_norm == "api" and not api_configured:
        warnings.append("web enrichment api 未配置，请接入API后使用")
        resources = _build_local_resources(documents, max_items=max_items)
        return {
            "enabled": True,
            "mode_requested": mode,
            "mode_effective": "local",
            "resources": resources,
            "warnings": warnings,
        }

    if mode_norm == "off":
        return {
            "enabled": True,
            "mode_requested": mode,
            "mode_effective": "off",
            "resources": [],
            "warnings": warnings,
        }

    if mode_norm == "local" or (mode_norm == "auto" and not api_configured):
        resources = _build_local_resources(documents, max_items=max_items)
        return {
            "enabled": True,
            "mode_requested": mode,
            "mode_effective": "local",
            "resources": resources,
            "warnings": warnings,
        }

    # API mode (explicit api or auto+configured)
    retries = max(0, int(api_retries))
    last_exc: Exception | None = None
    for _ in range(retries + 1):
        try:
            resources = _call_enrichment_api(
                documents,
                timeout_sec=timeout_sec,
                max_items=max_items,
            )
            return {
                "enabled": True,
                "mode_requested": mode,
                "mode_effective": "api",
                "resources": resources,
                "warnings": warnings,
            }
        except (
            RuntimeError,
            ValueError,
            error.URLError,
            error.HTTPError,
            json.JSONDecodeError,
        ) as exc:
            last_exc = exc
            continue
        except Exception as exc:
            last_exc = exc
            break

    if isinstance(
        last_exc,
        (RuntimeError, ValueError, error.URLError, error.HTTPError, json.JSONDecodeError),
    ):
        warnings.append(
            f"web enrichment api fallback after {retries + 1} attempt(s): {last_exc}"
        )
        resources = _build_local_resources(documents, max_items=max_items)
        return {
            "enabled": True,
            "mode_requested": mode,
            "mode_effective": "local",
            "resources": resources,
            "warnings": warnings,
        }

    warnings.append(
        f"web enrichment unexpected error after {retries + 1} attempt(s): {last_exc}"
    )
    return {
        "enabled": True,
        "mode_requested": mode,
        "mode_effective": "off",
        "resources": [],
        "warnings": warnings,
    }


if __name__ == "__main__":
    demo = [
        {
            "source_name": "demo.md",
            "extracted_text": "参考链接 https://example.com/guide",
        }
    ]
    print(json.dumps(web_enrich(demo, enabled=True, mode="local"), ensure_ascii=False, indent=2))
