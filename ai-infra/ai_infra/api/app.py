"""FastAPI backend for ai-infra -- REST + SSE endpoints."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import re
from collections.abc import AsyncIterator, Callable
from concurrent.futures import Future
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel as PydanticBaseModel
from sse_starlette.sse import EventSourceResponse

from ai_infra.generator.generator import TARGETS

app = FastAPI(
    title="ai-infra API",
    description="AI Infrastructure Generator API",
    version="0.1.0",
)

_LOCAL_HOST = r"(?:localhost|127\.0\.0\.1|\[::1\])(?::[0-9]{1,5})?"
_LOCAL_ORIGIN = r"https?://(?:localhost|127\.0\.0\.1|\[::1\])(?::[0-9]{1,5})?"

# Browser clients must be served from loopback origins.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=_LOCAL_ORIGIN,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger(__name__)


def _loopback_client(request: Request) -> bool:
    try:
        return request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        return False


@app.middleware("http")
async def protect_local_api(request: Request, call_next):
    hosts = request.headers.getlist("host")
    if len(hosts) != 1 or not re.fullmatch(_LOCAL_HOST, hosts[0], re.IGNORECASE):
        return JSONResponse(status_code=403, content={"detail": "Host is not allowed"})
    # CORS alone does not prevent a browser from sending a simple request.
    origins = request.headers.getlist("origin")
    if request.method != "OPTIONS":
        if origins and (len(origins) != 1 or not re.fullmatch(_LOCAL_ORIGIN, origins[0])):
            return JSONResponse(status_code=403, content={"detail": "Origin is not allowed"})
        if request.method == "POST" and not origins and not _loopback_client(request):
            return JSONResponse(status_code=403, content={"detail": "Origin required for non-loopback clients"})
    return await call_next(request)


def _allowed_path(path: str) -> Path:
    root = Path(os.environ.get("AI_INFRA_ALLOWED_ROOT", str(Path.cwd()))).expanduser().resolve()
    try:
        candidate = Path(path).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid path") from None
    if not candidate.is_relative_to(root):
        raise HTTPException(status_code=403, detail="Path is outside the allowed root")
    return candidate


def _repo_dir(repo_path: str) -> Path:
    repo = _allowed_path(repo_path)
    if not repo.is_dir():
        raise HTTPException(status_code=400, detail=f"Directory not found: {repo_path}")
    return repo


def _check_target(target: str) -> None:
    if target not in TARGETS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid target '{target}'. Choose from: {', '.join(TARGETS)}",
        )


# Jobs are started only by protected POST requests. Streams observe the same
# result on every connection, without running the operation again.
_jobs: dict[str, tuple[dict, Future]] = {}
_MAX_JOBS = 128


def _run_job(future: Future, work: Callable[[], Any]) -> None:
    try:
        result = work()
    except Exception as exc:
        logger.exception("Job failed")
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        future.set_result(("error", {"status": "error", "detail": detail}))
    else:
        future.set_result(("result", result))


def _start_job(background: BackgroundTasks, step: dict, work: Callable[[], Any]) -> dict:
    # Called by async routes, so registry changes are serialized on the event loop.
    if len(_jobs) >= _MAX_JOBS:
        for job_id, (_, future) in list(_jobs.items()):
            if future.done():
                del _jobs[job_id]
                break
        else:
            raise HTTPException(status_code=503, detail="Too many active jobs")
    job_id = uuid4().hex
    future: Future = Future()
    _jobs[job_id] = (step, future)
    background.add_task(_run_job, future, work)
    return {"job_id": job_id, "stream_url": f"/api/stream/{job_id}"}


@app.get("/api/stream/{job_id}")
async def job_stream(job_id: str) -> EventSourceResponse:
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    step, future = _jobs[job_id]

    async def event_generator() -> AsyncIterator[dict]:
        yield {"event": "status", "data": json.dumps(step)}
        event, result = await asyncio.shield(asyncio.wrap_future(future))
        yield {"event": event, "data": json.dumps(result)}
        if event == "result":
            yield {"event": "done", "data": json.dumps({"status": result.get("status", "ok")})}

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
    force: bool = False


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


@app.post("/api/jobs/analyze", status_code=202)
async def analyze_job(req: RepoRequest, background: BackgroundTasks) -> dict:
    _repo_dir(req.repo_path)
    return _start_job(background, {"step": "analyzing"}, lambda: analyze_endpoint(req))


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


@app.post("/api/jobs/plan", status_code=202)
async def plan_job(req: RepoRequest, background: BackgroundTasks) -> dict:
    _repo_dir(req.repo_path)
    return _start_job(background, {"step": "planning"}, lambda: plan_endpoint(req))


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


@app.post("/api/jobs/generate", status_code=202)
async def generate_job(req: GenerateRequest, background: BackgroundTasks) -> dict:
    _repo_dir(req.repo_path)
    _check_target(req.target)
    return _start_job(background, {"step": "generating", "target": req.target}, lambda: generate_endpoint(req))


# ---------------------------------------------------------------------------
# Fix
# ---------------------------------------------------------------------------


@app.post("/api/fix")
def fix_endpoint(req: FixRequest) -> dict:
    from ai_infra.fix.fix_loop import FixLoop

    repo = _repo_dir(req.repo_path)
    log_path = _allowed_path(req.log_path)

    if not log_path.is_file():
        raise HTTPException(status_code=400, detail=f"Log file not found: {req.log_path}")

    loop = FixLoop(repo)
    try:
        result = loop.fix(log_path, dry_run=req.dry_run, force=req.force)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from None

    return result


@app.post("/api/jobs/fix", status_code=202)
async def fix_job(req: FixRequest, background: BackgroundTasks) -> dict:
    _repo_dir(req.repo_path)
    if not _allowed_path(req.log_path).is_file():
        raise HTTPException(status_code=400, detail=f"Log file not found: {req.log_path}")
    return _start_job(background, {"step": "fixing"}, lambda: fix_endpoint(req))


def main() -> None:
    """Start the local API server."""
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, proxy_headers=False)


if __name__ == "__main__":
    main()
