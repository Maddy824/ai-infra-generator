"""FastAPI backend for ai-infra -- REST + SSE endpoints."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel as PydanticBaseModel
from sse_starlette.sse import EventSourceResponse
from starlette.concurrency import run_in_threadpool

from ai_infra.generator.generator import TARGETS

app = FastAPI(
    title="ai-infra API",
    description="AI Infrastructure Generator API",
    version="0.1.0",
)

# Browsers reject ``allow_credentials`` combined with a wildcard origin, and
# the API needs no cookies, so credentials stay off.  Restrict origins with
# a comma-separated AI_INFRA_CORS_ORIGINS (default: any origin).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("AI_INFRA_CORS_ORIGINS", "*").split(",")],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger(__name__)


def _repo_dir(repo_path: str) -> Path:
    repo = Path(repo_path)
    if not repo.is_dir():
        raise HTTPException(status_code=400, detail=f"Directory not found: {repo_path}")
    return repo


def _check_target(target: str) -> None:
    if target not in TARGETS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid target '{target}'. Choose from: {', '.join(TARGETS)}",
        )


def _stream(step: dict, work: Callable[[], Any]) -> EventSourceResponse:
    """Stream a ``status`` event, run blocking *work* off the event loop,
    then emit ``result`` + ``done`` -- or an ``error`` event if it fails.
    """

    async def event_generator() -> AsyncIterator[dict]:
        yield {"event": "status", "data": json.dumps(step)}
        try:
            result = await run_in_threadpool(work)
        except Exception as exc:  # noqa: BLE001 -- surfaced to the client
            logger.exception("Streaming step %s failed", step.get("step"))
            yield {"event": "error", "data": json.dumps({"status": "error", "detail": str(exc)})}
            return
        yield {"event": "result", "data": json.dumps(result)}
        yield {"event": "done", "data": json.dumps({"status": "ok"})}

    return EventSourceResponse(event_generator())


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class RepoRequest(PydanticBaseModel):
    repo_path: str


class GenerateRequest(PydanticBaseModel):
    repo_path: str
    target: str = "compose"
    force: bool = False


class FixRequest(PydanticBaseModel):
    repo_path: str
    log_path: str
    dry_run: bool = False


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Analyze
# ---------------------------------------------------------------------------


# Endpoints doing blocking work (filesystem, LLM calls) are plain ``def`` so
# FastAPI runs them in a worker thread instead of stalling the event loop.


@app.post("/api/analyze")
def analyze_endpoint(req: RepoRequest) -> dict:
    from ai_infra.analyzer.core import analyze

    repo = _repo_dir(req.repo_path)
    result = analyze(repo)
    return {"status": "ok", "result": result}


@app.get("/api/stream/analyze")
def analyze_stream(repo_path: str) -> EventSourceResponse:
    from ai_infra.analyzer.core import analyze

    repo = _repo_dir(repo_path)
    return _stream({"step": "analyzing"}, lambda: analyze(repo))


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


@app.post("/api/plan")
def plan_endpoint(req: RepoRequest) -> dict:
    from ai_infra.planner.planner import Planner
    from ai_infra.state.state_manager import StateManager

    repo = _repo_dir(req.repo_path)
    state = StateManager(repo)

    if not state.exists():
        raise HTTPException(status_code=400, detail="No .ai-infra/ directory. Run init first.")

    try:
        analyzer_output = state.read_analyzer_output()
    except FileNotFoundError:
        raise HTTPException(status_code=400, detail="No analyzer output. Run analyze first.") from None

    planner = Planner(repo)
    try:
        model = planner.plan(analyzer_output)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from None

    return {"status": "ok", "model": model.model_dump()}


@app.get("/api/stream/plan")
def plan_stream(repo_path: str) -> EventSourceResponse:
    from ai_infra.planner.planner import Planner
    from ai_infra.state.state_manager import StateManager

    repo = _repo_dir(repo_path)

    def work() -> dict:
        analyzer_output = StateManager(repo).read_analyzer_output()
        return Planner(repo).plan(analyzer_output).model_dump(mode="json")

    return _stream({"step": "planning"}, work)


# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------


@app.post("/api/generate")
def generate_endpoint(req: GenerateRequest) -> dict:
    from ai_infra.generator.generator import Generator
    from ai_infra.state.state_manager import StateManager

    repo = _repo_dir(req.repo_path)
    _check_target(req.target)

    state = StateManager(repo)
    try:
        model = state.read_infra_model()
    except FileNotFoundError:
        raise HTTPException(status_code=400, detail="No infra model. Run plan first.") from None

    gen = Generator(repo)
    files = gen.generate(model, target=req.target, force=req.force)

    return {
        "status": "ok",
        "target": req.target,
        "files": [str(f) for f in files],
        "skipped": [str(f) for f in gen.skipped],
    }


@app.get("/api/stream/generate")
def generate_stream(repo_path: str, target: str = "compose", force: bool = False) -> EventSourceResponse:
    from ai_infra.generator.generator import Generator
    from ai_infra.state.state_manager import StateManager

    repo = _repo_dir(repo_path)
    _check_target(target)

    def work() -> dict:
        model = StateManager(repo).read_infra_model()
        gen = Generator(repo)
        files = gen.generate(model, target=target, force=force)
        return {"files": [str(f) for f in files], "skipped": [str(f) for f in gen.skipped]}

    return _stream({"step": "generating", "target": target}, work)


# ---------------------------------------------------------------------------
# Fix
# ---------------------------------------------------------------------------


@app.post("/api/fix")
def fix_endpoint(req: FixRequest) -> dict:
    from ai_infra.fix.fix_loop import FixLoop

    repo = _repo_dir(req.repo_path)
    log_path = Path(req.log_path)

    if not log_path.is_file():
        raise HTTPException(status_code=400, detail=f"Log file not found: {req.log_path}")

    loop = FixLoop(repo)
    try:
        result = loop.fix(log_path, dry_run=req.dry_run)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from None

    return {"status": "ok", **result}


@app.get("/api/stream/fix")
def fix_stream(repo_path: str, log_path: str, dry_run: bool = False) -> EventSourceResponse:
    from ai_infra.fix.fix_loop import FixLoop

    repo = _repo_dir(repo_path)
    if not Path(log_path).is_file():
        raise HTTPException(status_code=400, detail=f"Log file not found: {log_path}")

    return _stream({"step": "fixing"}, lambda: FixLoop(repo).fix(Path(log_path), dry_run=dry_run))
