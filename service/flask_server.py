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

from typing import Any, Dict, List

from app import collect_input_files, run_pipeline
from tools.pipeline_runtime import (
    build_pipeline_run_kwargs,
    is_image_ocr_api_configured,
    is_topic_api_configured,
    is_web_enrichment_api_configured,
    load_local_env,
)

try:
    from flask import Flask, jsonify, request
except Exception as exc:  # pragma: no cover
    raise RuntimeError(
        "Flask dependencies missing. Install `requirements-flask.txt` first."
    ) from exc


# ---- .env auto-load (matches api_server.py behavior) ----------------------

load_local_env(".env")


# ---- request schema parser (stdlib, no pydantic) --------------------------

# Defaults intentionally identical to api_server.py::PipelineRequest so the
# two services are externally interchangeable.
_DEFAULTS: Dict[str, Any] = {
    "inputs": None,  # required
    "output_dir": "outputs",
    "config": "config/pipeline_config.json",
    "topic_taxonomy": "config/topic_taxonomy.json",
    "topic_mode": None,
    "topic_api_timeout": None,
    "topic_api_retries": None,
    "enable_web_enrichment": None,
    "web_enrichment_mode": None,
    "web_enrichment_timeout": None,
    "web_enrichment_max_items": None,
    "web_enrichment_api_retries": None,
    "enable_api_assist": None,
    "keypoint_min_confidence": None,
    "keypoint_max_points": None,
    "validation_profile": None,
    "export_docx": None,
    "full_report": None,
    "quiet": True,
}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off", ""}:
            return False
    raise ValueError(f"invalid boolean value: {value!r}")


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
        if out["topic_api_timeout"] is not None:
            out["topic_api_timeout"] = float(out["topic_api_timeout"])
        if out["web_enrichment_timeout"] is not None:
            out["web_enrichment_timeout"] = float(out["web_enrichment_timeout"])
        if out["keypoint_min_confidence"] is not None:
            out["keypoint_min_confidence"] = float(out["keypoint_min_confidence"])
        if out["topic_api_retries"] is not None:
            out["topic_api_retries"] = int(out["topic_api_retries"])
        if out["web_enrichment_max_items"] is not None:
            out["web_enrichment_max_items"] = int(out["web_enrichment_max_items"])
        if out["web_enrichment_api_retries"] is not None:
            out["web_enrichment_api_retries"] = int(out["web_enrichment_api_retries"])
        if out["keypoint_max_points"] is not None:
            out["keypoint_max_points"] = int(out["keypoint_max_points"])
        if out["enable_web_enrichment"] is not None:
            out["enable_web_enrichment"] = _as_bool(out["enable_web_enrichment"])
        if out["enable_api_assist"] is not None:
            out["enable_api_assist"] = _as_bool(out["enable_api_assist"])
        if out["export_docx"] is not None:
            out["export_docx"] = _as_bool(out["export_docx"])
        if out["full_report"] is not None:
            out["full_report"] = _as_bool(out["full_report"])
        out["quiet"] = _as_bool(out["quiet"])
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
                "topic_api_configured": is_topic_api_configured(),
                "web_enrichment_api_configured": is_web_enrichment_api_configured(),
                "image_ocr_api_configured": is_image_ocr_api_configured(),
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
        run_kwargs, _meta = build_pipeline_run_kwargs(
            config_path=req["config"],
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
            validation_profile=req["validation_profile"],
            export_docx=req["export_docx"],
            full_report=bool(req["full_report"]),
        )
        result = run_pipeline(
            files,
            output_dir=req["output_dir"],
            topic_taxonomy_path=req["topic_taxonomy"],
            **run_kwargs,
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
