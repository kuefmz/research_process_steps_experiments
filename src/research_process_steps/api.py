"""Minimal FastAPI interface for deterministic repository experiments."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .analyzer import DEFAULT_CONTENT_LIMIT, analyze_github_repository


class AnalyzeRequest(BaseModel):
    repo_url: str = Field(..., examples=["https://github.com/KnowledgeCaptureAndDiscovery/somef"])
    ref: str | None = None
    max_content_bytes: int = Field(
        default=DEFAULT_CONTENT_LIMIT,
        ge=0,
        le=2_000_000,
        description="Maximum size of a file whose textual contents are inspected.",
    )


app = FastAPI(
    title="Research Process Steps Heuristic API",
    description=(
        "Deterministic, no-AI API that maps files in a GitHub repository to "
        "research process steps and returns the exact heuristic evidence."
    ),
    version="0.1.0",
)

WEB_DIR = Path(__file__).with_name("web")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "method": "deterministic_heuristics",
        "uses_ai": False,
    }


@app.post("/api/analyze")
def analyze(request: AnalyzeRequest) -> dict[str, Any]:
    try:
        return analyze_github_repository(
            request.repo_url,
            token=os.getenv("GITHUB_TOKEN"),
            ref=request.ref,
            max_content_bytes=request.max_content_bytes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Repository analysis failed: {exc}",
        ) from exc


@app.get("/", include_in_schema=False)
def interface() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


def run() -> None:
    """Run the local experimentation web interface."""
    import uvicorn

    uvicorn.run(
        "research_process_steps.api:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )
