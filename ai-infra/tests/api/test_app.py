"""Tests for the FastAPI backend."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_infra.api.app import app
from ai_infra.state.state_manager import StateManager


@pytest.fixture()
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    # sse-starlette keeps a module-level exit event bound to the first event
    # loop that used it; each TestClient runs its own loop, so reset it.
    from sse_starlette.sse import AppStatus

    AppStatus.should_exit_event = None
    monkeypatch.setenv("AI_INFRA_ALLOWED_ROOT", str(tmp_path))
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 12345)) as local:
        yield local


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
    resp = client.post("/api/jobs/generate", json={"repo_path": str(tmp_path), "target": "nope"})
    assert resp.status_code == 400


def test_stream_reports_errors_as_events(client, tmp_repo_with_state: Path):
    # No analyzer output yet -> planning fails; the stream must say so.
    job = client.post("/api/jobs/plan", json={"repo_path": str(tmp_repo_with_state)})
    assert job.status_code == 202
    resp = client.get(job.json()["stream_url"])
    assert resp.status_code == 200
    assert "event: error" in resp.text
    assert "event: done" not in resp.text


def test_stream_analyze_emits_result(client, fastapi_app_dir: Path):
    job = client.post("/api/jobs/analyze", json={"repo_path": str(fastapi_app_dir)})
    assert job.status_code == 202
    resp = client.get(job.json()["stream_url"])
    assert "event: result" in resp.text
    assert "event: done" in resp.text


@pytest.mark.parametrize("origin", ["http://localhost:3000", "https://127.0.0.1:5173", "http://[::1]:8000"])
def test_localhost_cors_allowed(client, origin):
    response = client.options("/api/analyze", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST",
    })
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


@pytest.mark.parametrize("origin", ["https://example.test", "http://localhost.example.test", "null"])
def test_remote_cors_denied(client, origin):
    response = client.options("/api/analyze", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST",
    })
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_remote_origin_cannot_create_job(client, tmp_path):
    response = client.post("/api/jobs/analyze", json={"repo_path": str(tmp_path)},
                          headers={"Origin": "https://example.test"})
    assert response.status_code == 403
    assert not (tmp_path / ".ai-infra").exists()


@pytest.mark.parametrize("endpoint", ["analyze", "plan", "generate", "fix"])
@pytest.mark.parametrize("stream", [False, True])
def test_all_endpoints_refuse_outside_repo(client, tmp_path, monkeypatch, endpoint, stream):
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "allowed-other"
    outside.mkdir()
    monkeypatch.setenv("AI_INFRA_ALLOWED_ROOT", str(root))
    payload = {"repo_path": str(root / ".." / outside.name)}
    if endpoint == "fix":
        payload["log_path"] = str(outside / "error.log")
    if stream:
        response = client.post(f"/api/jobs/{endpoint}", json=payload)
    else:
        response = client.post(f"/api/{endpoint}", json=payload)
    assert response.status_code == 403
    assert not (outside / ".ai-infra").exists()


def test_symlink_to_outside_repo_denied(client, tmp_path, monkeypatch):
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "link"
    link.symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("AI_INFRA_ALLOWED_ROOT", str(root))
    assert client.post("/api/analyze", json={"repo_path": str(link)}).status_code == 403


def test_root_defaults_to_working_directory(client, tmp_path, monkeypatch):
    root = tmp_path / "allowed"
    root.mkdir()
    monkeypatch.chdir(root)
    monkeypatch.delenv("AI_INFRA_ALLOWED_ROOT")
    assert client.post("/api/analyze", json={"repo_path": "."}).status_code == 200
    assert client.post("/api/analyze", json={"repo_path": ".."}).status_code == 403


def test_fix_refuses_log_outside_root(client, tmp_path, monkeypatch):
    root = tmp_path / "allowed"
    root.mkdir()
    log = tmp_path / "error.log"
    log.write_text("error")
    monkeypatch.setenv("AI_INFRA_ALLOWED_ROOT", str(root))
    payload = {"repo_path": str(root), "log_path": str(log)}
    assert client.post("/api/fix", json=payload).status_code == 403
    assert client.post("/api/jobs/fix", json=payload).status_code == 403


def test_server_binds_to_loopback(monkeypatch):
    from ai_infra.api.app import main

    calls = []
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: calls.append(kwargs))
    main()
    assert calls == [{"host": "127.0.0.1", "port": 8000, "proxy_headers": False}]


@pytest.mark.parametrize("host", ["localhost:8000", "127.0.0.1", "[::1]:8000", "LOCALHOST"])
def test_local_hosts_allowed(client, host):
    assert client.get("/health", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize("host", ["example.test", "localhost.example.test", "localhost@other.test", ""])
def test_nonlocal_hosts_rejected(client, tmp_path, host):
    assert client.post("/api/analyze", json={"repo_path": str(tmp_path)},
                       headers={"Host": host}).status_code == 403
    assert client.get("/health", headers={"Host": host}).status_code == 403
    assert not (tmp_path / ".ai-infra").exists()


@pytest.mark.parametrize("prefix", ["/api", "/api/jobs"])
def test_mutations_require_local_origin_or_loopback(tmp_path, client, prefix):
    remote = TestClient(app, base_url="http://localhost", client=("192.0.2.1", 12345))
    payload = {"repo_path": str(tmp_path)}
    assert remote.post(f"{prefix}/analyze", json=payload).status_code == 403
    assert remote.post(f"{prefix}/analyze", json=payload, headers={"Origin": "null"}).status_code == 403
    assert not (tmp_path / ".ai-infra").exists()
    response = remote.post(f"{prefix}/analyze", json=payload, headers={"Origin": "http://localhost:3000"})
    assert response.status_code in (200, 202)
    assert (tmp_path / ".ai-infra/analyzer_output.json").exists()


@pytest.mark.parametrize("operation", ["analyze", "plan", "generate", "fix"])
def test_get_cannot_create_job(client, tmp_path, operation):
    params = {"repo_path": str(tmp_path)}
    assert client.get(f"/api/stream/{operation}", params=params).status_code == 404
    assert client.get(f"/api/jobs/{operation}", params=params).status_code == 405
    assert not (tmp_path / ".ai-infra").exists()


def test_stream_reconnect_does_not_repeat_work(client, fastapi_app_dir, monkeypatch):
    from ai_infra.analyzer import core

    calls = []
    original = core.analyze

    def record(repo):
        calls.append(repo)
        return original(repo)

    monkeypatch.setattr(core, "analyze", record)
    job = client.post("/api/jobs/analyze", json={"repo_path": str(fastapi_app_dir)})
    assert job.status_code == 202
    url = job.json()["stream_url"]
    first = client.get(url)
    second = client.get(url)
    assert first.status_code == second.status_code == 200
    assert first.text == second.text
    assert "event: status" in first.text
    assert "event: result" in first.text
    assert "event: done" in first.text
    assert calls == [fastapi_app_dir.resolve()]


def test_analyzer_rejects_external_file_even_inside_api_allowed_root(client, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text('[project]\ndependencies = ["flask"]\n')
    outside = tmp_path / "requirements.txt"
    outside.write_text("redis\n")
    (repo / "requirements.txt").symlink_to(outside)
    response = client.post("/api/analyze", json={"repo_path": str(repo)})
    assert response.status_code == 200
    assert response.json()["result"]["dependencies"]["raw"] == ["flask"]
    assert StateManager(repo).read_analyzer_output()["dependencies"]["inferred_services"] == []


def test_fix_stream_reconnect_preserves_one_application(client, tmp_repo_with_state, sample_model):
    state = StateManager(tmp_repo_with_state)
    state.write_infra_model(sample_model)
    log = tmp_repo_with_state / "crash.log"
    log.write_text("container=web OOMKilled\n")
    payload = {"repo_path": str(tmp_repo_with_state), "log_path": str(log)}
    job = client.post("/api/jobs/fix", json=payload)
    assert job.status_code == 202
    applied = state.read_infra_model()
    assert applied != sample_model
    url = job.json()["stream_url"]
    assert '"status": "applied"' in client.get(url).text
    assert '"status": "applied"' in client.get(url).text
    assert state.read_infra_model() == applied
