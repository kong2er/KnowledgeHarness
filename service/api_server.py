"""Minimal FastAPI service entry for KnowledgeHarness.

Scope:
- Exposes current CLI pipeline as HTTP endpoints.
- Keeps the same degradation semantics as `app.run_pipeline`.
- Does not change core processing logic.
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
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel, Field
except Exception as exc:  # pragma: no cover
    raise RuntimeError(
        "FastAPI dependencies missing. Install `requirements-api.txt` first."
    ) from exc


class PipelineRequest(BaseModel):
    inputs: List[str] = Field(..., description="Input files/dirs/globs")
    output_dir: str = "outputs"
    config: str = "config/pipeline_config.json"
    topic_taxonomy: str = "config/topic_taxonomy.json"
    topic_mode: str | None = None
    topic_api_timeout: float | None = None
    topic_api_retries: int | None = None
    enable_web_enrichment: bool | None = None
    web_enrichment_mode: str | None = None
    web_enrichment_timeout: float | None = None
    web_enrichment_max_items: int | None = None
    web_enrichment_api_retries: int | None = None
    enable_api_assist: bool | None = None
    keypoint_min_confidence: float | None = None
    keypoint_max_points: int | None = None
    validation_profile: str | None = None
    export_docx: bool | None = None
    full_report: bool | None = None
    quiet: bool = True


app = FastAPI(title="KnowledgeHarness API", version="0.1.0")


load_local_env(".env")


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "knowledgeharness-api",
        "features": {
            "topic_api_configured": is_topic_api_configured(),
            "web_enrichment_api_configured": is_web_enrichment_api_configured(),
            "image_ocr_api_configured": is_image_ocr_api_configured(),
        },
    }


@app.post("/pipeline/run")
def pipeline_run(req: PipelineRequest) -> Dict[str, Any]:
    files = collect_input_files(req.inputs)
    if not files:
        raise HTTPException(status_code=400, detail="No valid input files found")

    run_kwargs, _meta = build_pipeline_run_kwargs(
        config_path=req.config,
        topic_mode=req.topic_mode,
        topic_api_timeout=req.topic_api_timeout,
        topic_api_retries=req.topic_api_retries,
        web_enrichment_enabled=req.enable_web_enrichment,
        web_enrichment_mode=req.web_enrichment_mode,
        web_enrichment_timeout=req.web_enrichment_timeout,
        web_enrichment_max_items=req.web_enrichment_max_items,
        web_enrichment_api_retries=req.web_enrichment_api_retries,
        api_assist_enabled=req.enable_api_assist,
        keypoint_min_confidence=req.keypoint_min_confidence,
        keypoint_max_points=req.keypoint_max_points,
        validation_profile=req.validation_profile,
        export_docx=req.export_docx,
        full_report=bool(req.full_report),
    )
    result = run_pipeline(
        files,
        output_dir=req.output_dir,
        topic_taxonomy_path=req.topic_taxonomy,
        **run_kwargs,
    )

    return {
        "ok": True,
        "api_notice": "API 协助默认关闭；如需启用请传 enable_api_assist=true",
        "result": result,
    }


@app.get("/pipeline/capabilities")
def capabilities() -> Dict[str, Any]:
    return {
        "mode": "minimal_service_entry",
        "notes": [
            "This service wraps the existing CLI pipeline only.",
            "External API integration still depends on your real endpoint spec.",
        ],
    }
