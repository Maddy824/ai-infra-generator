"""Tests for the FastAPI backend."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_infra.api.app import app
from ai_infra.state.state_manager import StateManager


@pytest.fixture()
def client() -> TestClient:
    # sse-starlette keeps a module-level exit event bound to the first event
    # loop that used it; each TestClient runs its own loop, so reset it.
    from sse_starlette.sse import AppStatus

    AppStatus.should_exit_event = None
    return TestClient(app)


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_analyze_missing_dir_is_400(client, tmp_path: Path):
    resp = client.post("/api/analyze", json={"repo_path": str(tmp_path / "nope")})
    assert resp.status_code == 400


def test_analyze_returns_result(client, fastapi_app_dir: Path):
    resp = client.post("/api/analyze", json={"repo_path": str(fastapi_app_dir)})
    assert resp.status_code == 200
    assert resp.json()["result"]["language"] == "python"


def test_generate_invalid_target_is_400(client, tmp_path: Path):
    resp = client.post("/api/generate", json={"repo_path": str(tmp_path), "target": "nope"})
    assert resp.status_code == 400
    assert "Invalid target" in resp.json()["detail"]


def test_generate_writes_files(client, tmp_repo_with_state: Path, sample_model):
    StateManager(tmp_repo_with_state).write_infra_model(sample_model)
    resp = client.post(
        "/api/generate", json={"repo_path": str(tmp_repo_with_state), "target": "compose"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["files"]
    assert body["skipped"] == []


def test_stream_generate_invalid_target_is_400(client, tmp_path: Path):
    resp = client.get("/api/stream/generate", params={"repo_path": str(tmp_path), "target": "nope"})
    assert resp.status_code == 400


def test_stream_reports_errors_as_events(client, tmp_repo_with_state: Path):
    # No analyzer output yet -> planning fails; the stream must say so.
    resp = client.get("/api/stream/plan", params={"repo_path": str(tmp_repo_with_state)})
    assert resp.status_code == 200
    assert "event: error" in resp.text
    assert "event: done" not in resp.text


def test_stream_analyze_emits_result(client, fastapi_app_dir: Path):
    resp = client.get("/api/stream/analyze", params={"repo_path": str(fastapi_app_dir)})
    assert "event: result" in resp.text
    assert "event: done" in resp.text
