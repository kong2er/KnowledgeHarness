"""Runtime configuration loader for KnowledgeHarness.

Loads a JSON config and merges onto safe defaults.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Tuple

DEFAULT_CONFIG: Dict[str, Any] = {
    "chunking": {"max_chars": 500},
    "classification": {
        "category_priority": [
            "difficult_or_error_prone_points",
            "extended_reading",
            "methods_and_processes",
            "examples_and_applications",
            "basic_concepts",
        ]
    },
    "key_points": {"max_points": 12, "min_confidence": 0.0},
    "topic": {"mode": "auto", "api_timeout_sec": 6.0, "api_retries": 1},
    "web_enrichment": {
        "enabled": False,
        "mode": "auto",
        "timeout_sec": 6.0,
        "max_items": 8,
        "api_retries": 1,
    },
    "api_assist": {"enabled_by_default": False},
    "ocr": {"languages": "chi_sim+eng", "fallback_language": "eng"},
    "export": {"markdown_use_details": False},
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_runtime_config(config_path: str | None = None) -> Tuple[Dict[str, Any], list[str]]:
    warnings: list[str] = []
    if not config_path:
        return deepcopy(DEFAULT_CONFIG), warnings

    path = Path(config_path)
    if not path.exists():
        warnings.append(f"runtime config not found: {config_path}; using defaults")
        return deepcopy(DEFAULT_CONFIG), warnings

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        warnings.append(f"runtime config parse failed: {config_path} ({exc}); using defaults")
        return deepcopy(DEFAULT_CONFIG), warnings

    if not isinstance(raw, dict):
        warnings.append(f"runtime config root must be object: {config_path}; using defaults")
        return deepcopy(DEFAULT_CONFIG), warnings

    merged = _deep_merge(DEFAULT_CONFIG, raw)
    return merged, warnings


if __name__ == "__main__":
    conf, warns = load_runtime_config("config/pipeline_config.json")
    print(json.dumps({"warnings": warns, "config": conf}, ensure_ascii=False, indent=2))
