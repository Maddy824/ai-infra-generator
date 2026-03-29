"""FastAPI backend for ai-infra -- REST + SSE endpoints."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel as PydanticBaseModel
from sse_starlette.sse import EventSourceResponse

app = FastAPI(
    title="ai-infra API",
    description="AI Infrastructure Generator API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger(__name__)


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


@app.post("/api/analyze")
async def analyze_endpoint(req: RepoRequest) -> dict:
    from ai_infra.analyzer.core import analyze

    repo = Path(req.repo_path)
    if not repo.is_dir():
        raise HTTPException(status_code=400, detail=f"Directory not found: {req.repo_path}")

    result = analyze(repo)
    return {"status": "ok", "result": result}


@app.get("/api/stream/analyze")
async def analyze_stream(repo_path: str):
    from ai_infra.analyzer.core import analyze

    async def event_generator():
        repo = Path(repo_path)
        yield {"event": "status", "data": json.dumps({"step": "analyzing"})}
        result = analyze(repo)
        yield {"event": "result", "data": json.dumps(result)}
        yield {"event": "done", "data": json.dumps({"status": "ok"})}

    return EventSourceResponse(event_generator())


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


@app.post("/api/plan")
async def plan_endpoint(req: RepoRequest) -> dict:
    from ai_infra.planner.planner import Planner
    from ai_infra.state.state_manager import StateManager

    repo = Path(req.repo_path)
    state = StateManager(repo)

    if not state.exists():
        raise HTTPException(status_code=400, detail="No .ai-infra/ directory. Run init first.")

    try:
        analyzer_output = state.read_analyzer_output()
    except FileNotFoundError:
        raise HTTPException(status_code=400, detail="No analyzer output. Run analyze first.")

    planner = Planner(repo)
    try:
        model = planner.plan(analyzer_output)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {"status": "ok", "model": model.model_dump()}


@app.get("/api/stream/plan")
async def plan_stream(repo_path: str):
    from ai_infra.planner.planner import Planner
    from ai_infra.state.state_manager import StateManager

    async def event_generator():
        repo = Path(repo_path)
        state = StateManager(repo)
        yield {"event": "status", "data": json.dumps({"step": "planning"})}

        analyzer_output = state.read_analyzer_output()
        planner = Planner(repo)
        model = planner.plan(analyzer_output)

        yield {"event": "result", "data": model.model_dump_json()}
        yield {"event": "done", "data": json.dumps({"status": "ok"})}

    return EventSourceResponse(event_generator())


# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------


@app.post("/api/generate")
async def generate_endpoint(req: GenerateRequest) -> dict:
    from ai_infra.generator.generator import Generator
    from ai_infra.state.state_manager import StateManager

    repo = Path(req.repo_path)

    valid_targets = {"compose", "k8s", "ci", "helm", "iac", "monitoring", "tenancy", "all"}
    if req.target not in valid_targets:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid target '{req.target}'. Choose from: {', '.join(sorted(valid_targets))}",
        )

    state = StateManager(repo)
    try:
        model = state.read_infra_model()
    except FileNotFoundError:
        raise HTTPException(status_code=400, detail="No infra model. Run plan first.")

    gen = Generator(repo)
    files = gen.generate(model, target=req.target, force=req.force)

    return {
        "status": "ok",
        "target": req.target,
        "files": [str(f) for f in files],
    }


@app.get("/api/stream/generate")
async def generate_stream(repo_path: str, target: str = "compose"):
    from ai_infra.generator.generator import Generator
    from ai_infra.state.state_manager import StateManager

    async def event_generator():
        repo = Path(repo_path)
        state = StateManager(repo)
        yield {"event": "status", "data": json.dumps({"step": "generating", "target": target})}

        model = state.read_infra_model()
        gen = Generator(repo)
        files = gen.generate(model, target=target, force=True)

        yield {"event": "result", "data": json.dumps({"files": [str(f) for f in files]})}
        yield {"event": "done", "data": json.dumps({"status": "ok"})}

    return EventSourceResponse(event_generator())


# ---------------------------------------------------------------------------
# Fix
# ---------------------------------------------------------------------------


@app.post("/api/fix")
async def fix_endpoint(req: FixRequest) -> dict:
    from ai_infra.fix.fix_loop import FixLoop

    repo = Path(req.repo_path)
    log_path = Path(req.log_path)

    if not log_path.is_file():
        raise HTTPException(status_code=400, detail=f"Log file not found: {req.log_path}")

    loop = FixLoop(repo)
    try:
        result = loop.fix(log_path, dry_run=req.dry_run)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {"status": "ok", **result}


@app.get("/api/stream/fix")
async def fix_stream(repo_path: str, log_path: str, dry_run: bool = False):
    from ai_infra.fix.fix_loop import FixLoop

    async def event_generator():
        repo = Path(repo_path)
        yield {"event": "status", "data": json.dumps({"step": "fixing"})}

        loop = FixLoop(repo)
        result = loop.fix(Path(log_path), dry_run=dry_run)

        yield {"event": "result", "data": json.dumps(result)}
        yield {"event": "done", "data": json.dumps({"status": "ok"})}

    return EventSourceResponse(event_generator())
