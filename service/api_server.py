"""Minimal FastAPI service entry for KnowledgeHarness.

Scope:
- Exposes current CLI pipeline as HTTP endpoints.
- Keeps the same degradation semantics as `app.run_pipeline`.
- Does not change core processing logic.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

from app import collect_input_files, run_pipeline

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
    topic_mode: str = "auto"
    topic_api_timeout: float = 6.0
    topic_api_retries: int = 1
    enable_web_enrichment: bool = False
    web_enrichment_mode: str = "auto"
    web_enrichment_timeout: float = 6.0
    web_enrichment_max_items: int = 8
    keypoint_min_confidence: float = 0.0
    keypoint_max_points: int = 12
    quiet: bool = True


app = FastAPI(title="KnowledgeHarness API", version="0.1.0")


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


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "knowledgeharness-api",
        "features": {
            "topic_api_configured": bool(os.getenv("TOPIC_CLASSIFIER_API_URL", "").strip()),
            "web_enrichment_api_configured": bool(
                os.getenv("WEB_ENRICHMENT_API_URL", "").strip()
            ),
        },
    }


@app.post("/pipeline/run")
def pipeline_run(req: PipelineRequest) -> Dict[str, Any]:
    files = collect_input_files(req.inputs)
    if not files:
        raise HTTPException(status_code=400, detail="No valid input files found")

    result = run_pipeline(
        files,
        output_dir=req.output_dir,
        topic_taxonomy_path=req.topic_taxonomy,
        topic_mode=req.topic_mode,
        topic_api_timeout=req.topic_api_timeout,
        topic_api_retries=req.topic_api_retries,
        web_enrichment_enabled=req.enable_web_enrichment,
        web_enrichment_mode=req.web_enrichment_mode,
        web_enrichment_timeout=req.web_enrichment_timeout,
        web_enrichment_max_items=req.web_enrichment_max_items,
        keypoint_min_confidence=req.keypoint_min_confidence,
        keypoint_max_points=req.keypoint_max_points,
    )

    return {
        "ok": True,
        "api_notice": "请接入API后使用",
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
