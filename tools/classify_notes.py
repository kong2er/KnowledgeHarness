"""Rule-based chunk classification for KnowledgeHarness.

Classification policy (acceptance baseline):
- Only emit labels from CATEGORIES.
- Tie-break by CATEGORY_PRIORITY instead of dropping to `unclassified`;
  confidence is penalized so ambiguous items still surface in review_needed.
- A leading "label phrase" (e.g. "概念：", "易错点：") gives a strong bonus
  because that mirrors how real study notes are authored.
- Chunks with zero keyword hits fall into `unclassified` and review_needed.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Tuple, Optional
from urllib import parse, request

CATEGORIES = [
    "basic_concepts",
    "methods_and_processes",
    "examples_and_applications",
    "difficult_or_error_prone_points",
    "extended_reading",
    "unclassified",
]

# Priority order used when multiple categories tie on score.
# Rationale: explicit "pitfall" and "reading" markers are the most unambiguous
# signals users leave in notes, so they beat the broader method/example/concept
# buckets during a tie-break.
CATEGORY_PRIORITY = [
    "difficult_or_error_prone_points",
    "extended_reading",
    "methods_and_processes",
    "examples_and_applications",
    "basic_concepts",
]

KEYWORDS: Dict[str, List[str]] = {
    "basic_concepts": [
        "定义", "概念", "本质", "是什么", "原理", "含义",
        "definition", "concept", "principle",
    ],
    "methods_and_processes": [
        "步骤", "流程", "方法", "算法", "过程", "实现",
        "how to", "process", "method", "procedure", "algorithm",
    ],
    "examples_and_applications": [
        "例如", "例子", "案例", "应用", "场景", "实战", "举例", "demo",
        "example", "application", "case",
    ],
    "difficult_or_error_prone_points": [
        "易错", "难点", "注意", "陷阱", "坑", "常见错误", "误区",
        "warning", "pitfall", "caveat", "gotcha",
    ],
    "extended_reading": [
        "扩展阅读", "延伸阅读", "参考", "参考资料", "链接", "论文", "官方",
        "read more", "resource", "reference", "further reading",
        "http://", "https://",
    ],
}

# Label hints are matched against the leading "xxx：" prefix only.
# A chunk starting with "概念：..." is a much stronger signal than the same
# keyword appearing somewhere inside a long paragraph.
LABEL_HINTS: Dict[str, List[str]] = {
    "basic_concepts": ["概念", "定义", "本质", "原理"],
    "methods_and_processes": ["方法", "步骤", "流程", "过程"],
    "examples_and_applications": ["例如", "例子", "案例", "应用", "举例", "实战"],
    "difficult_or_error_prone_points": ["易错", "难点", "注意", "坑", "陷阱", "误区"],
    "extended_reading": ["扩展阅读", "延伸阅读", "参考"],
}

# Match a short "label" that precedes a Chinese or ASCII colon at chunk start,
# tolerating leading markdown heading marks (# / ## / ...).
_LABEL_RE = re.compile(r"^\s*#*\s*([^\s：:]{2,8})\s*[：:]")
DEFAULT_API_TEMPLATE_PATH = (
    os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "config",
        "api_payload_templates.json",
    )
)


def _leading_label(text: str) -> str | None:
    match = _LABEL_RE.match(text or "")
    return match.group(1) if match else None


def _load_classify_api_template() -> Dict[str, Any]:
    template_path = os.getenv("CONTENT_CLASSIFIER_API_TEMPLATE", DEFAULT_API_TEMPLATE_PATH)
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        section = raw.get("content_classifier", {}) if isinstance(raw, dict) else {}
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


def _call_classification_api(
    *,
    text: str,
    allowed_categories: List[str],
    timeout_sec: float,
) -> Dict[str, Any]:
    url = (
        os.getenv("CONTENT_CLASSIFIER_API_URL", "").strip()
        or os.getenv("KNOWLEDGEHARNESS_API_URL", "").strip()
    )
    if not url:
        raise RuntimeError("CONTENT_CLASSIFIER_API_URL is not configured")

    api_template = _load_classify_api_template()
    system_prompt = str(api_template.get("system_prompt") or "").strip()
    output_contract = (
        api_template.get("output_contract")
        if isinstance(api_template.get("output_contract"), dict)
        else {
            "category": "string",
            "confidence": "number between 0 and 1",
            "reason": "short string",
        }
    )
    payload = {
        "text": text,
        "allowed_categories": allowed_categories,
        "system_prompt": system_prompt
        or (
            "You are a constrained content classifier. "
            "Choose category only from allowed_categories."
        ),
        "output_contract": output_contract,
        "rules": {
            "must_choose_from_allowed_categories": True,
            "fallback_category": "unclassified",
        },
    }

    headers = {"Content-Type": "application/json"}
    api_key = (
        os.getenv("CONTENT_CLASSIFIER_API_KEY", "").strip()
        or os.getenv("KNOWLEDGEHARNESS_API_KEY", "").strip()
    )
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    style = _resolve_api_style(url, "CONTENT_CLASSIFIER_API_STYLE")
    request_url = url
    request_payload: Dict[str, Any]
    if style == "openai_compatible":
        request_url = _resolve_openai_endpoint(url)
        model = (
            os.getenv("CONTENT_CLASSIFIER_API_MODEL", "").strip()
            or os.getenv("KNOWLEDGEHARNESS_API_MODEL", "").strip()
            or "deepseek-chat"
        )
        request_payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": payload["system_prompt"]
                    + " 只允许返回 JSON 对象，字段为 category/confidence/reason。",
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "text": payload["text"],
                            "allowed_categories": payload["allowed_categories"],
                            "rules": payload["rules"],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": 0.1,
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

    category = str(data.get("category") or "").strip()
    confidence = float(data.get("confidence") or 0.0)
    reason = str(data.get("reason") or f"api assisted ({style})")
    if category not in allowed_categories:
        raise ValueError(f"api returned out-of-scope category: {category}")
    confidence = max(0.0, min(1.0, confidence))
    return {"category": category, "confidence": confidence, "reason": reason}


def _score_chunk(
    chunk_text: str,
    keywords: Dict[str, List[str]],
    label_hints: Dict[str, List[str]],
) -> Dict[str, int]:
    text_lower = (chunk_text or "").lower()
    scores = {k: 0 for k in keywords}

    # Body-level keyword matching (weak evidence, +1 per hit).
    for category, words in keywords.items():
        for w in words:
            if w.lower() in text_lower:
                scores[category] += 1

    # Leading-label matching (strong evidence, +3 once per category).
    label = _leading_label(chunk_text or "")
    if label:
        for category, hints in label_hints.items():
            for hint in hints:
                if hint in label:
                    scores[category] += 3
                    break  # cap: at most one label bonus per category

    return scores


def _priority_of(category: str, category_priority: List[str]) -> int:
    try:
        return category_priority.index(category)
    except ValueError:
        return len(category_priority)


def _choose_category(
    scores: Dict[str, int],
    category_priority: List[str],
) -> Tuple[str, float, str]:
    # Sort: higher score first; break ties by category priority.
    ordered = sorted(
        scores.items(),
        key=lambda item: (-item[1], _priority_of(item[0], category_priority)),
    )
    best_cat, best_score = ordered[0]
    second_score = ordered[1][1] if len(ordered) > 1 else 0

    if best_score <= 0:
        return "unclassified", 0.0, "no keyword matched"

    # Stepped confidence. A body-only single hit (score=1) barely passes the
    # review_needed threshold (0.4), while a label-hit (>=3) is trusted.
    if best_score >= 4:
        confidence = 1.0
    elif best_score == 3:
        confidence = 0.85
    elif best_score == 2:
        confidence = 0.6
    else:
        confidence = 0.4

    if best_score == second_score:
        # Tie: keep the priority-elected category, but flag for review.
        return best_cat, confidence * 0.75, "tie resolved by category priority"

    return best_cat, confidence, "rule-based keyword match"


def classify_notes(
    chunks: List[Dict[str, Any]],
    keywords: Optional[Dict[str, List[str]]] = None,
    label_hints: Optional[Dict[str, List[str]]] = None,
    category_priority: Optional[List[str]] = None,
    api_assist_enabled: bool = False,
    api_timeout_sec: float = 6.0,
    api_retries: int = 1,
) -> Dict[str, Any]:
    """Classify chunks and produce review_needed for low-confidence items."""
    keywords = keywords or KEYWORDS
    label_hints = label_hints or LABEL_HINTS
    category_priority = category_priority or CATEGORY_PRIORITY

    categorized: Dict[str, List[Dict[str, Any]]] = {c: [] for c in CATEGORIES}
    review_needed: List[Dict[str, Any]] = []
    enriched_chunks: List[Dict[str, Any]] = []
    warnings: List[str] = []
    retries = max(0, int(api_retries))
    api_configured = bool(
        os.getenv("CONTENT_CLASSIFIER_API_URL", "").strip()
        or os.getenv("KNOWLEDGEHARNESS_API_URL", "").strip()
    )
    if api_assist_enabled and not api_configured:
        warnings.append("content classifier api 未配置，请接入API后使用")

    for chunk in chunks:
        text = chunk.get("chunk_text", "")
        scores = _score_chunk(text, keywords=keywords, label_hints=label_hints)
        category, confidence, reason = _choose_category(
            scores,
            category_priority=category_priority,
        )
        used_api = False
        api_attempts = 0
        fallback_state = "none"

        should_try_api = bool(api_assist_enabled and (category == "unclassified" or confidence < 0.85))
        if should_try_api and api_configured:
            last_exc: Exception | None = None
            for _ in range(retries + 1):
                api_attempts += 1
                try:
                    api_out = _call_classification_api(
                        text=text,
                        allowed_categories=CATEGORIES,
                        timeout_sec=api_timeout_sec,
                    )
                    api_category = str(api_out["category"])
                    api_conf = float(api_out["confidence"])
                    api_reason = str(api_out["reason"])
                    # Use API result when it improves confidence or resolves unclassified.
                    if (category == "unclassified" and api_category != "unclassified") or (api_conf >= confidence):
                        category = api_category
                        confidence = api_conf
                        reason = f"{reason}; api refined: {api_reason}"
                    used_api = True
                    break
                except Exception as exc:
                    last_exc = exc
                    continue
            if not used_api and last_exc is not None:
                fallback_state = "api_to_local"
                warnings.append(
                    f"content classify api fallback for {chunk.get('chunk_id')} after {api_attempts} attempt(s): {last_exc}"
                )

        item = {
            **chunk,
            "category": category,
            "confidence": round(confidence, 3),
            "classification_reason": reason,
            "keyword_scores": scores,
            "used_api": used_api,
            "api_attempts": api_attempts,
            "fallback_state": fallback_state,
        }
        if category not in categorized:
            item["category"] = "unclassified"
            item["classification_reason"] = "out-of-scope category normalized"
            item["confidence"] = 0.0
            category = "unclassified"
        categorized[category].append(item)
        enriched_chunks.append(item)

        if category == "unclassified" or confidence < 0.4:
            review_needed.append(
                {
                    "chunk_id": item["chunk_id"],
                    "source_name": item.get("source_name"),
                    "reason": "low confidence classification",
                    "detail": reason,
                    "chunk_text": text,
                }
            )

    return {
        "chunks": enriched_chunks,
        "categorized": categorized,
        "review_needed": review_needed,
        "warnings": warnings,
        "stats": {
            "chunk_count": len(chunks),
            "used_api_count": sum(1 for x in enriched_chunks if x.get("used_api")),
        },
    }


if __name__ == "__main__":
    import json

    demo = [{"chunk_id": "000-0000", "chunk_text": "这个概念的定义是什么？"}]
    print(json.dumps(classify_notes(demo), ensure_ascii=False, indent=2))
