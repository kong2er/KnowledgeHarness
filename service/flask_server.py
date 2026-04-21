"""Minimal Flask service entry for KnowledgeHarness.

Scope:
- Mirrors the three endpoints exposed by `service/api_server.py`
  (the FastAPI entry) so ops teams can pick whichever framework
  their stack standardizes on.
- Reuses `app.run_pipeline` unchanged — no core-logic fork.
- Same degradation semantics as CLI / FastAPI (failed sources →
  `failed_sources[*].reason`; topic/web API failure → pipeline_notes
  via run_pipeline; no-input → HTTP 400).
- Optional dependency: install via `requirements-flask.txt`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

from app import collect_input_files, run_pipeline

try:
    from flask import Flask, jsonify, request
except Exception as exc:  # pragma: no cover
    raise RuntimeError(
        "Flask dependencies missing. Install `requirements-flask.txt` first."
    ) from exc


# ---- .env auto-load (matches api_server.py behavior) ----------------------

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


_load_local_env(".env")


# ---- request schema parser (stdlib, no pydantic) --------------------------

# Defaults intentionally identical to api_server.py::PipelineRequest so the
# two services are externally interchangeable.
_DEFAULTS: Dict[str, Any] = {
    "inputs": None,  # required
    "output_dir": "outputs",
    "config": "config/pipeline_config.json",
    "topic_taxonomy": "config/topic_taxonomy.json",
    "topic_mode": "auto",
    "topic_api_timeout": 6.0,
    "topic_api_retries": 1,
    "enable_web_enrichment": False,
    "web_enrichment_mode": "auto",
    "web_enrichment_timeout": 6.0,
    "web_enrichment_max_items": 8,
    "web_enrichment_api_retries": 1,
    "enable_api_assist": False,
    "keypoint_min_confidence": 0.0,
    "keypoint_max_points": 12,
    "quiet": True,
}


def _parse_pipeline_request(payload: Any) -> Dict[str, Any]:
    """Validate + coerce the JSON body into the shape run_pipeline expects.

    Raises ValueError with a user-facing message on bad input.
    """
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")

    out: Dict[str, Any] = {}
    for key, default in _DEFAULTS.items():
        if key in payload:
            out[key] = payload[key]
        else:
            out[key] = default

    inputs = out["inputs"]
    if not isinstance(inputs, list) or not inputs:
        raise ValueError("'inputs' must be a non-empty list of file/dir/glob strings")
    for item in inputs:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("'inputs[*]' must be non-empty strings")

    # minimal type coercion — let run_pipeline surface deeper issues
    try:
        out["topic_api_timeout"] = float(out["topic_api_timeout"])
        out["web_enrichment_timeout"] = float(out["web_enrichment_timeout"])
        out["keypoint_min_confidence"] = float(out["keypoint_min_confidence"])
        out["topic_api_retries"] = int(out["topic_api_retries"])
        out["web_enrichment_max_items"] = int(out["web_enrichment_max_items"])
        out["web_enrichment_api_retries"] = int(out["web_enrichment_api_retries"])
        out["keypoint_max_points"] = int(out["keypoint_max_points"])
        out["enable_web_enrichment"] = bool(out["enable_web_enrichment"])
        out["enable_api_assist"] = bool(out["enable_api_assist"])
        out["quiet"] = bool(out["quiet"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid numeric/boolean field: {exc}") from exc

    return out


# ---- Flask app -------------------------------------------------------------

app = Flask("knowledgeharness-flask")


@app.get("/health")
def health() -> Any:
    return jsonify(
        {
            "status": "ok",
            "service": "knowledgeharness-flask",
            "features": {
                "topic_api_configured": bool(
                    os.getenv("TOPIC_CLASSIFIER_API_URL", "").strip()
                ),
                "web_enrichment_api_configured": bool(
                    os.getenv("WEB_ENRICHMENT_API_URL", "").strip()
                ),
            },
        }
    )


@app.post("/pipeline/run")
def pipeline_run() -> Any:
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"invalid JSON body: {exc}"}), 400

    try:
        req = _parse_pipeline_request(payload)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    files = collect_input_files(req["inputs"])
    if not files:
        return (
            jsonify({"ok": False, "error": "No valid input files found"}),
            400,
        )

    try:
        result = run_pipeline(
            files,
            output_dir=req["output_dir"],
            topic_taxonomy_path=req["topic_taxonomy"],
            topic_mode=req["topic_mode"],
            topic_api_timeout=req["topic_api_timeout"],
            topic_api_retries=req["topic_api_retries"],
            web_enrichment_enabled=req["enable_web_enrichment"],
            web_enrichment_mode=req["web_enrichment_mode"],
            web_enrichment_timeout=req["web_enrichment_timeout"],
            web_enrichment_max_items=req["web_enrichment_max_items"],
            web_enrichment_api_retries=req["web_enrichment_api_retries"],
            api_assist_enabled=req["enable_api_assist"],
            keypoint_min_confidence=req["keypoint_min_confidence"],
            keypoint_max_points=req["keypoint_max_points"],
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": f"pipeline error: {exc}"}), 500

    return jsonify(
        {
            "ok": True,
            "api_notice": "API 协助默认关闭；如需启用请传 enable_api_assist=true",
            "result": result,
        }
    )


@app.get("/pipeline/capabilities")
def capabilities() -> Any:
    return jsonify(
        {
            "mode": "minimal_service_entry",
            "framework": "flask",
            "notes": [
                "This service wraps the existing CLI pipeline only.",
                "External API integration still depends on your real endpoint spec.",
                "Interchangeable with service/api_server.py (FastAPI) — same request schema.",
            ],
        }
    )


# ---- CLI runner for `python3 service/flask_server.py` ---------------------

def main() -> None:  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(description="KnowledgeHarness Flask service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    # debug=False in production; Flask dev server is fine for a minimal entry
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":  # pragma: no cover
    main()
