"""Shared runtime helpers for CLI/API/UI pipeline entrypoints.

This module keeps cross-entry behavior aligned:
- local `.env` loading (without overriding existing process env)
- API configuration readiness probes
- runtime-config + request/form override resolution for `run_pipeline`
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Tuple

from tools.runtime_config import load_runtime_config

UNIFIED_API_URL_KEY = "KNOWLEDGEHARNESS_API_URL"
TOPIC_API_URL_KEY = "TOPIC_CLASSIFIER_API_URL"
WEB_API_URL_KEY = "WEB_ENRICHMENT_API_URL"
IMAGE_OCR_API_URL_KEY = "IMAGE_OCR_API_URL"


def load_local_env(path: str = ".env") -> None:
    """Load KEY=VALUE pairs from a local .env file.

    Existing process env takes precedence: if KEY already exists in
    `os.environ`, this loader keeps the current value unchanged.
    """
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


def _env_is_set(key: str) -> bool:
    return bool(os.getenv(key, "").strip())


def is_topic_api_configured() -> bool:
    """True if topic-classifier API is configured (specific or unified key)."""
    return _env_is_set(TOPIC_API_URL_KEY) or _env_is_set(UNIFIED_API_URL_KEY)


def is_web_enrichment_api_configured() -> bool:
    """True if web-enrichment API is configured (specific or unified key)."""
    return _env_is_set(WEB_API_URL_KEY) or _env_is_set(UNIFIED_API_URL_KEY)


def is_image_ocr_api_configured() -> bool:
    """True if image OCR API is configured (specific or unified key)."""
    return _env_is_set(IMAGE_OCR_API_URL_KEY) or _env_is_set(UNIFIED_API_URL_KEY)


def is_any_api_configured() -> bool:
    """True if any optional API-assist URL is configured."""
    return (
        is_topic_api_configured()
        or is_web_enrichment_api_configured()
        or is_image_ocr_api_configured()
    )


def _pick(override: Any, fallback: Any) -> Any:
    return fallback if override is None else override


def build_pipeline_run_kwargs(
    *,
    config_path: str = "config/pipeline_config.json",
    topic_mode: str | None = None,
    topic_api_timeout: float | None = None,
    topic_api_retries: int | None = None,
    web_enrichment_enabled: bool | None = None,
    web_enrichment_mode: str | None = None,
    web_enrichment_timeout: float | None = None,
    web_enrichment_max_items: int | None = None,
    web_enrichment_api_retries: int | None = None,
    api_assist_enabled: bool | None = None,
    keypoint_min_confidence: float | None = None,
    keypoint_max_points: int | None = None,
    validation_profile: str | None = None,
    export_docx: bool | None = None,
    full_report: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Resolve runtime config + per-entry overrides into run_pipeline kwargs.

    Returns:
        (run_kwargs, meta)
        - run_kwargs: ready to spread into `run_pipeline(...)`
        - meta: derived execution flags useful for notices / health display
    """
    runtime_conf, conf_warnings = load_runtime_config(config_path)
    topic_conf = runtime_conf.get("topic", {}) or {}
    web_conf = runtime_conf.get("web_enrichment", {}) or {}
    api_assist_conf = runtime_conf.get("api_assist", {}) or {}
    key_conf = runtime_conf.get("key_points", {}) or {}
    validation_conf = runtime_conf.get("validation", {}) or {}
    chunk_conf = runtime_conf.get("chunking", {}) or {}
    cls_conf = runtime_conf.get("classification", {}) or {}
    ocr_conf = runtime_conf.get("ocr", {}) or {}
    export_conf = runtime_conf.get("export", {}) or {}

    topic_mode_effective = str(_pick(topic_mode, topic_conf.get("mode", "auto")))
    web_mode_effective = str(
        _pick(web_enrichment_mode, web_conf.get("mode", "auto"))
    )
    web_enabled_effective = bool(
        _pick(web_enrichment_enabled, web_conf.get("enabled", False))
    )
    api_assist_effective = bool(
        _pick(api_assist_enabled, api_assist_conf.get("enabled_by_default", False))
    )
    validation_profile_effective = str(
        _pick(validation_profile, validation_conf.get("profile", "strict"))
    ).strip().lower()
    if validation_profile_effective not in {"strict", "lenient"}:
        conf_warnings.append(
            f"invalid validation profile '{validation_profile_effective}', fallback to strict"
        )
        validation_profile_effective = "strict"

    run_kwargs: Dict[str, Any] = {
        "topic_mode": topic_mode_effective,
        "topic_api_timeout": float(
            _pick(topic_api_timeout, topic_conf.get("api_timeout_sec", 6.0))
        ),
        "topic_api_retries": int(
            _pick(topic_api_retries, topic_conf.get("api_retries", 1))
        ),
        "web_enrichment_enabled": web_enabled_effective,
        "web_enrichment_mode": web_mode_effective,
        "web_enrichment_timeout": float(
            _pick(web_enrichment_timeout, web_conf.get("timeout_sec", 6.0))
        ),
        "web_enrichment_max_items": int(
            _pick(web_enrichment_max_items, web_conf.get("max_items", 8))
        ),
        "web_enrichment_api_retries": int(
            _pick(web_enrichment_api_retries, web_conf.get("api_retries", 1))
        ),
        "api_assist_enabled": api_assist_effective,
        "keypoint_min_confidence": float(
            _pick(keypoint_min_confidence, key_conf.get("min_confidence", 0.0))
        ),
        "keypoint_max_points": int(
            _pick(keypoint_max_points, key_conf.get("max_points", 12))
        ),
        "validation_profile": validation_profile_effective,
        "chunk_max_chars": int(chunk_conf.get("max_chars", 500)),
        "classification_keywords": cls_conf.get("keywords"),
        "classification_label_hints": cls_conf.get("label_hints"),
        "classification_category_priority": cls_conf.get("category_priority"),
        "ocr_languages": str(ocr_conf.get("languages", "chi_sim+eng")),
        "ocr_fallback_language": str(ocr_conf.get("fallback_language", "eng")),
        "image_api_timeout_sec": float(ocr_conf.get("api_timeout_sec", 8.0)),
        "image_api_retries": int(ocr_conf.get("api_retries", 1)),
        "image_api_enhance_mode": str(ocr_conf.get("api_enhance_mode", "auto")),
        "image_api_enhance_min_score": int(ocr_conf.get("api_enhance_min_score", 40)),
        "image_api_enhance_ratio": float(ocr_conf.get("api_enhance_ratio", 1.1)),
        "image_api_enhance_min_delta": int(ocr_conf.get("api_enhance_min_delta", 6)),
        "markdown_use_details": bool(export_conf.get("markdown_use_details", False)),
        "final_notes_only": (not bool(full_report))
        and bool(export_conf.get("final_notes_only", True)),
        "export_docx": bool(_pick(export_docx, export_conf.get("export_docx", False))),
        "pre_pipeline_notes": [f"runtime config warning: {w}" for w in conf_warnings],
    }

    meta: Dict[str, Any] = {
        "topic_mode": topic_mode_effective,
        "web_enrichment_mode": web_mode_effective,
        "web_enrichment_enabled": web_enabled_effective,
        "api_assist_enabled": api_assist_effective,
        "validation_profile": validation_profile_effective,
        "has_topic_api": is_topic_api_configured(),
        "has_web_api": is_web_enrichment_api_configured(),
        "has_any_api": is_any_api_configured(),
        "runtime_config_warnings": conf_warnings,
    }
    return run_kwargs, meta
