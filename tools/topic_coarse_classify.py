"""Topic coarse classification layer for KnowledgeHarness.

This module classifies each source document into one constrained topic label.
It is intentionally separate from chunk-level content-type classification.

Design goals:
- Labels must come from a local allowed set (config/topic_taxonomy.json).
- Optional API assistance is bounded by the same local label set.
- On any uncertainty/failure, degrade to `unknown_topic` without crashing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib import error, request

UNKNOWN_TOPIC = "unknown_topic"
DEFAULT_TAXONOMY_PATH = Path(__file__).resolve().parent.parent / "config" / "topic_taxonomy.json"
DEFAULT_API_TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "api_payload_templates.json"
)


def _load_topic_api_template() -> Dict[str, Any]:
    template_path = Path(
        os.getenv("TOPIC_CLASSIFIER_API_TEMPLATE", str(DEFAULT_API_TEMPLATE_PATH))
    )
    try:
        raw = json.loads(template_path.read_text(encoding="utf-8"))
        section = raw.get("topic_classifier", {}) if isinstance(raw, dict) else {}
        if not isinstance(section, dict):
            return {}
        return section
    except Exception:
        return {}


def _load_taxonomy(taxonomy_path: str | None = None) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Load label definitions from local JSON taxonomy.

    Returns:
        (labels, warnings)
    """
    warnings: List[str] = []
    path = Path(taxonomy_path) if taxonomy_path else DEFAULT_TAXONOMY_PATH

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        warnings.append(
            f"topic taxonomy load failed: {path} ({exc}); fallback to [{UNKNOWN_TOPIC}]"
        )
        return [
            {
                "label_id": UNKNOWN_TOPIC,
                "display_name": "Unknown Topic",
                "aliases": [],
            }
        ], warnings

    labels = raw.get("labels", []) if isinstance(raw, dict) else []
    normalized: List[Dict[str, Any]] = []
    seen = set()
    for item in labels:
        if not isinstance(item, dict):
            continue
        label_id = str(item.get("label_id", "")).strip()
        if not label_id or label_id in seen:
            continue
        seen.add(label_id)
        aliases = item.get("aliases", []) or []
        aliases = [str(x).strip() for x in aliases if str(x).strip()]
        normalized.append(
            {
                "label_id": label_id,
                "display_name": str(item.get("display_name") or label_id),
                "aliases": aliases,
            }
        )

    if not normalized:
        warnings.append(
            f"topic taxonomy empty or invalid: {path}; fallback to [{UNKNOWN_TOPIC}]"
        )
        normalized = [
            {
                "label_id": UNKNOWN_TOPIC,
                "display_name": "Unknown Topic",
                "aliases": [],
            }
        ]

    if UNKNOWN_TOPIC not in {x["label_id"] for x in normalized}:
        normalized.append(
            {
                "label_id": UNKNOWN_TOPIC,
                "display_name": "Unknown Topic",
                "aliases": [],
            }
        )
        warnings.append("topic taxonomy missing unknown_topic; auto-appended")

    return normalized, warnings


def _local_rule_classify(text: str, labels: List[Dict[str, Any]]) -> Tuple[str, float, str]:
    text_l = (text or "").lower()
    scores: Dict[str, int] = {item["label_id"]: 0 for item in labels}

    for item in labels:
        label_id = item["label_id"]
        if label_id == UNKNOWN_TOPIC:
            continue
        for token in item.get("aliases", []) or []:
            if token.lower() in text_l:
                scores[label_id] += 1

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_label, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0

    if best_score <= 0 or best_label == UNKNOWN_TOPIC:
        return UNKNOWN_TOPIC, 0.0, "no topic hint matched"

    if best_score >= 3:
        conf = 0.9
    elif best_score == 2:
        conf = 0.7
    else:
        conf = 0.5

    if best_score == second_score:
        return UNKNOWN_TOPIC, 0.0, "ambiguous topic signals (tie)"

    return best_label, conf, "local alias match"


def _call_topic_api(
    text: str,
    labels: List[Dict[str, Any]],
    timeout_sec: float,
) -> Dict[str, Any]:
    """Call optional external topic classifier endpoint.

    Required envs:
    - TOPIC_CLASSIFIER_API_URL
    Optional env:
    - TOPIC_CLASSIFIER_API_KEY

    API response should be JSON with shape:
    {"topic_label": "...", "confidence": 0.0-1.0, "reason": "..."}
    """
    url = os.getenv("TOPIC_CLASSIFIER_API_URL", "").strip()
    if not url:
        raise RuntimeError("TOPIC_CLASSIFIER_API_URL is not configured")

    allowed = [x["label_id"] for x in labels]
    api_template = _load_topic_api_template()
    system_prompt = str(api_template.get("system_prompt") or "").strip()
    output_contract = (
        api_template.get("output_contract")
        if isinstance(api_template.get("output_contract"), dict)
        else {
            "topic_label": "string",
            "confidence": "number between 0 and 1",
            "reason": "short string",
        }
    )
    payload = {
        "text": text,
        "allowed_labels": allowed,
        "label_hints": labels,
        "system_prompt": system_prompt
        or (
            "Select topic_label from allowed_labels only. "
            f"If unsure, return {UNKNOWN_TOPIC}."
        ),
        "output_contract": output_contract,
        "rules": {
            "must_choose_from_allowed_labels": True,
            "fallback_label": UNKNOWN_TOPIC,
        },
    }

    headers = {"Content-Type": "application/json"}
    api_key = os.getenv("TOPIC_CLASSIFIER_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = request.Request(
        url=url,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
    )

    with request.urlopen(req, timeout=timeout_sec) as resp:
        body = resp.read().decode("utf-8", errors="replace")

    data = json.loads(body)
    label = str(data.get("topic_label") or "").strip()
    confidence = data.get("confidence")
    reason = str(data.get("reason") or "api assisted")

    if label not in allowed:
        raise ValueError(f"api returned out-of-scope label: {label}")

    if not isinstance(confidence, (int, float)):
        confidence = 0.0 if label == UNKNOWN_TOPIC else 0.5

    return {
        "topic_label": label,
        "confidence": float(max(0.0, min(1.0, confidence))),
        "reason": reason,
    }


def topic_coarse_classify(
    documents: List[Dict[str, Any]],
    taxonomy_path: str | None = None,
    mode: str = "auto",
    api_timeout_sec: float = 6.0,
    api_retries: int = 1,
) -> Dict[str, Any]:
    """Classify documents into coarse topic labels.

    mode:
    - "local": always use local rules only
    - "api": API first; fallback to local/unknown
    - "auto": API if configured, otherwise local
    """
    labels, warnings = _load_taxonomy(taxonomy_path)
    allowed_labels = [x["label_id"] for x in labels]
    api_url_configured = bool(os.getenv("TOPIC_CLASSIFIER_API_URL", "").strip())
    retries = max(0, int(api_retries))

    mode_norm = (mode or "auto").strip().lower()
    if mode_norm not in {"auto", "local", "api"}:
        mode_norm = "auto"
        warnings.append("invalid topic mode; fallback to auto")
    if mode_norm == "api" and not api_url_configured:
        warnings.append("topic api 未配置，请接入API后使用")

    items: List[Dict[str, Any]] = []
    topic_groups: Dict[str, List[str]] = {label: [] for label in allowed_labels}

    for doc in documents:
        text = (doc.get("extracted_text") or doc.get("raw_text") or "").strip()
        source_name = doc.get("source_name")
        source_path = doc.get("source_path")
        source_type = doc.get("source_type")

        label = UNKNOWN_TOPIC
        confidence = 0.0
        reason = "empty text"
        used_api = False
        fallback_state = "none"
        api_attempts = 0

        if text:
            should_try_api = mode_norm == "api" or (
                mode_norm == "auto" and api_url_configured
            )
            if should_try_api:
                last_exc: Exception | None = None
                for _ in range(retries + 1):
                    api_attempts += 1
                    try:
                        api_result = _call_topic_api(text, labels, timeout_sec=api_timeout_sec)
                        label = api_result["topic_label"]
                        confidence = api_result["confidence"]
                        reason = api_result["reason"]
                        used_api = True
                        last_exc = None
                        break
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

                if last_exc is None:
                    pass
                elif isinstance(
                    last_exc,
                    (RuntimeError, ValueError, error.URLError, error.HTTPError, json.JSONDecodeError),
                ):
                    fallback_state = "api_to_local"
                    warnings.append(
                        f"topic api fallback for {source_name} after {api_attempts} attempt(s): {last_exc}"
                    )
                    label, confidence, reason = _local_rule_classify(text, labels)
                    reason = f"{reason}; api fallback: {last_exc}"
                else:
                    fallback_state = "api_to_unknown"
                    warnings.append(
                        f"topic api unexpected error for {source_name} after {api_attempts} attempt(s): {last_exc}"
                    )
                    label, confidence, reason = UNKNOWN_TOPIC, 0.0, f"api error: {last_exc}"
            else:
                label, confidence, reason = _local_rule_classify(text, labels)

        if label not in topic_groups:
            # Should not happen due to strict checks; keep safe fallback anyway.
            warnings.append(
                f"out-of-scope topic label normalized to unknown for {source_name}: {label}"
            )
            label = UNKNOWN_TOPIC
            confidence = 0.0
            reason = "label normalized to unknown_topic"
            fallback_state = "invalid_label_to_unknown"

        topic_groups[label].append(str(source_name))
        items.append(
            {
                "source_name": source_name,
                "source_path": source_path,
                "source_type": source_type,
                "topic_label": label,
                "confidence": round(float(confidence), 3),
                "reason": reason,
                "used_api": used_api,
                "api_attempts": api_attempts,
                "fallback_state": fallback_state,
            }
        )

    if not documents:
        warnings.append("topic coarse classification skipped: no parsed documents")

    counts = {label: len(names) for label, names in topic_groups.items()}
    used_api_count = sum(1 for x in items if x.get("used_api"))
    degraded_count = sum(1 for x in items if x.get("fallback_state") not in {"none", ""})

    return {
        "mode_requested": mode_norm,
        "allowed_labels": allowed_labels,
        "label_definitions": labels,
        "items": items,
        "topic_groups": topic_groups,
        "stats": {
            "document_count": len(documents),
            "used_api_count": used_api_count,
            "degraded_count": degraded_count,
            "counts_by_label": counts,
        },
        "warnings": warnings,
    }


if __name__ == "__main__":
    demo_docs = [
        {
            "source_name": "demo.md",
            "source_path": "/tmp/demo.md",
            "source_type": "md",
            "extracted_text": "线性代数与概率论复习提纲",
        }
    ]
    print(json.dumps(topic_coarse_classify(demo_docs), ensure_ascii=False, indent=2))
