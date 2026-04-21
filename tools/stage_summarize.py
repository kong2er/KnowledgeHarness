"""Stage summarization for KnowledgeHarness."""

from __future__ import annotations

from collections import Counter
import json
import os
import re
from typing import Any, Dict, List
from urllib import parse, request


CATEGORIES = [
    "basic_concepts",
    "methods_and_processes",
    "examples_and_applications",
    "difficult_or_error_prone_points",
    "extended_reading",
    "unclassified",
]
DEFAULT_API_TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "config",
    "api_payload_templates.json",
)


def _load_stage3_api_template() -> Dict[str, Any]:
    template_path = os.getenv("NOTES_ORGANIZER_API_TEMPLATE", DEFAULT_API_TEMPLATE_PATH)
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        section = raw.get("notes_organizer", {}) if isinstance(raw, dict) else {}
        return section if isinstance(section, dict) else {}
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
        data = json.loads(snippet)
        if isinstance(data, dict):
            return data
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


def _call_stage3_api(
    *,
    classified: Dict[str, List[Dict[str, Any]]],
    timeout_sec: float,
) -> Dict[str, List[str]]:
    url = (
        os.getenv("NOTES_ORGANIZER_API_URL", "").strip()
        or os.getenv("KNOWLEDGEHARNESS_API_URL", "").strip()
    )
    if not url:
        raise RuntimeError("NOTES_ORGANIZER_API_URL is not configured")

    def _top(cat: str, n: int = 8) -> List[str]:
        return [str(c.get("chunk_text", "")).strip() for c in classified.get(cat, [])[:n] if str(c.get("chunk_text", "")).strip()]

    api_template = _load_stage3_api_template()
    payload = {
        "categorized_notes": {
            "basic_concepts": _top("basic_concepts"),
            "methods_and_processes": _top("methods_and_processes"),
            "difficult_or_error_prone_points": _top("difficult_or_error_prone_points"),
            "extended_reading": _top("extended_reading"),
        },
        "output_contract": (
            api_template.get("output_contract")
            if isinstance(api_template.get("output_contract"), dict)
            else {
                "must_remember_concepts": "string[]",
                "high_priority_points": "string[]",
                "easy_to_confuse_points": "string[]",
                "next_reading_directions": "string[]",
            }
        ),
        "rules": {
            "only_use_user_material": True,
            "do_not_invent_new_facts": True,
            "max_items_per_list": 8,
        },
        "system_prompt": str(api_template.get("system_prompt") or "").strip()
        or (
            "你是受约束的学习笔记整理器。仅基于输入笔记，输出固定 JSON 结构。"
            "不得虚构新事实。"
        ),
    }

    headers = {"Content-Type": "application/json"}
    api_key = (
        os.getenv("NOTES_ORGANIZER_API_KEY", "").strip()
        or os.getenv("KNOWLEDGEHARNESS_API_KEY", "").strip()
    )
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    style = _resolve_api_style(url, "NOTES_ORGANIZER_API_STYLE")
    request_url = url
    request_payload: Dict[str, Any]
    if style == "openai_compatible":
        request_url = _resolve_openai_endpoint(url)
        model = (
            os.getenv("NOTES_ORGANIZER_API_MODEL", "").strip()
            or os.getenv("KNOWLEDGEHARNESS_API_MODEL", "").strip()
            or "deepseek-chat"
        )
        request_payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": payload["system_prompt"] + " 只允许返回 JSON 对象。",
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "categorized_notes": payload["categorized_notes"],
                            "output_contract": payload["output_contract"],
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
        content = str(((choices[0] or {}).get("message") or {}).get("content") or "")
        data = _extract_json_object_from_text(content)

    if not isinstance(data, dict):
        raise ValueError("stage3 api returned invalid payload")
    out: Dict[str, List[str]] = {}
    for key in [
        "must_remember_concepts",
        "high_priority_points",
        "easy_to_confuse_points",
        "next_reading_directions",
    ]:
        raw = data.get(key, [])
        vals = raw if isinstance(raw, list) else []
        cleaned = [str(x).strip() for x in vals if str(x).strip()][:8]
        out[key] = cleaned
    return out


def stage_summarize(
    documents: List[Dict[str, Any]],
    classified: Dict[str, List[Dict[str, Any]]],
    api_assist_enabled: bool = False,
    api_timeout_sec: float = 6.0,
    api_retries: int = 1,
) -> Dict[str, Any]:
    """Generate 3-stage baseline summaries."""
    source_count = len(documents)

    theme_counter = Counter()
    for cat in CATEGORIES:
        theme_counter[cat] = len(classified.get(cat, []))

    missing_themes = [k for k, v in theme_counter.items() if v == 0 and k != "unclassified"]

    stage_1 = {
        "name": "Stage 1: Overview",
        "source_count": source_count,
        "theme_distribution": dict(theme_counter),
        "potentially_missing_themes": missing_themes,
        "summary_text": (
            f"Processed {source_count} sources. "
            f"Top theme counts: {dict(theme_counter)}. "
            f"Potentially missing themes: {missing_themes or 'none'}."
        ),
    }

    category_summaries = {}
    for cat in CATEGORIES:
        items = classified.get(cat, [])
        preview = [i.get("chunk_text", "")[:120] for i in items[:3]]
        category_summaries[cat] = {
            "count": len(items),
            "preview": preview,
        }

    stage_2 = {
        "name": "Stage 2: Category Summary",
        "categories": category_summaries,
    }

    stage_3 = {
        "name": "Stage 3: Final Key Notes",
        "must_remember_concepts": [c.get("chunk_text", "") for c in classified.get("basic_concepts", [])[:5]],
        "high_priority_points": [c.get("chunk_text", "") for c in classified.get("methods_and_processes", [])[:5]],
        "easy_to_confuse_points": [
            c.get("chunk_text", "") for c in classified.get("difficult_or_error_prone_points", [])[:5]
        ],
        "next_reading_directions": [c.get("chunk_text", "") for c in classified.get("extended_reading", [])[:5]],
    }
    warnings: List[str] = []
    used_api = False
    api_attempts = 0
    fallback_state = "none"
    api_configured = bool(
        os.getenv("NOTES_ORGANIZER_API_URL", "").strip()
        or os.getenv("KNOWLEDGEHARNESS_API_URL", "").strip()
    )

    if api_assist_enabled:
        if not api_configured:
            warnings.append("notes organizer api 未配置，请接入API后使用")
            fallback_state = "api_not_configured"
        else:
            retries = max(0, int(api_retries))
            last_exc: Exception | None = None
            for _ in range(retries + 1):
                api_attempts += 1
                try:
                    api_stage3 = _call_stage3_api(
                        classified=classified,
                        timeout_sec=api_timeout_sec,
                    )
                    stage_3.update(api_stage3)
                    used_api = True
                    break
                except Exception as exc:
                    last_exc = exc
                    continue
            if not used_api and last_exc is not None:
                fallback_state = "api_to_local"
                warnings.append(
                    f"stage summarize api fallback after {api_attempts} attempt(s): {last_exc}"
                )

    stage_3["used_api"] = used_api
    stage_3["api_attempts"] = api_attempts
    stage_3["fallback_state"] = fallback_state

    return {
        "stage_1": stage_1,
        "stage_2": stage_2,
        "stage_3": stage_3,
        "warnings": warnings,
    }


if __name__ == "__main__":
    import json

    print(
        json.dumps(
            stage_summarize([], {k: [] for k in CATEGORIES}),
            ensure_ascii=False,
            indent=2,
        )
    )
