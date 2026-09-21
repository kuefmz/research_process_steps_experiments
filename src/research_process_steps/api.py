"""Minimal FastAPI interface for deterministic repository experiments."""

from __future__ import annotations

import hashlib
import json
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
CACHE_VERSION = "v2"
CACHE_DIR = Path(
    os.getenv(
        "RPS_CACHE_DIR",
        str(Path.home() / ".cache" / "research_process_steps"),
    )
)
DEMO_REPOSITORIES = {
    "https://github.com/knowledgecaptureanddiscovery/somef",
    "https://github.com/dgarijo/widoco",
}


def _normalize_repo_url(repo_url: str) -> str:
    return repo_url.rstrip("/").removesuffix(".git").lower()


def _demo_cache_path(request: AnalyzeRequest) -> Path | None:
    normalized = _normalize_repo_url(request.repo_url)
    if (
        normalized not in DEMO_REPOSITORIES
        or request.ref is not None
        or request.max_content_bytes != DEFAULT_CONTENT_LIMIT
    ):
        return None

    key = hashlib.sha256(
        f"{CACHE_VERSION}|{normalized}".encode("utf-8")
    ).hexdigest()[:16]
    return CACHE_DIR / f"{key}.json"


def _load_cache(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    payload["cache"] = {
        "hit": True,
        "persistent": True,
        "path": str(path),
    }
    return payload


def _save_cache(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cached = dict(payload)
    cached["cache"] = {
        "hit": False,
        "persistent": True,
        "path": str(path),
    }
    path.write_text(
        json.dumps(cached, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


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
        cache_path = _demo_cache_path(request)
        if cache_path is not None:
            cached = _load_cache(cache_path)
            if cached is not None:
                return cached

        result = analyze_github_repository(
            request.repo_url,
            token=os.getenv("GITHUB_TOKEN"),
            ref=request.ref,
            max_content_bytes=request.max_content_bytes,
        )
        result["cache"] = {
            "hit": False,
            "persistent": cache_path is not None,
            "path": str(cache_path) if cache_path is not None else None,
        }
        if cache_path is not None:
            _save_cache(cache_path, result)
        return result
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
