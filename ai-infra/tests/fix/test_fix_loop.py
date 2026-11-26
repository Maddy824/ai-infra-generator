"""Tests for the FixLoop module — log parsing and deterministic patching."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_infra.fix.fix_loop import FixLoop, parse_logs
from ai_infra.generator.generator import Generator
from ai_infra.models.infra_model import (
    InfraModel,
    LiteralEnv,
    PortMapping,
    RoutingModel,
    SecretEnv,
    ServiceModel,
    SizingModel,
    VolumeMount,
)
from ai_infra.state.state_manager import StateManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_model(memory_limits: str = "512Mi") -> InfraModel:
    return InfraModel(
        project_name="fix-test",
        routing=RoutingModel(domain="localhost"),
        services=[
            ServiceModel(
                name="web",
                type="app",
                image="python:3.11-slim",
                entrypoint="uvicorn main:app --host 0.0.0.0 --port 8000",
                ports=[PortMapping(container=8000, host=8000)],
                depends_on=[],
                env={"DATABASE_URL": LiteralEnv(value="postgres://u:p@postgres:5432/db")},
                sizing=SizingModel(memory_limits=memory_limits),
            ),
            ServiceModel(
                name="postgres",
                type="database",
                image="postgres:16-alpine",
                ports=[PortMapping(container=5432, host=5432)],
                env={"POSTGRES_PASSWORD": SecretEnv(ref="POSTGRES_PASSWORD")},
                sizing=SizingModel(),
                volumes=[VolumeMount(name="pgdata", mount_path="/var/lib/postgresql/data")],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------


class TestLogParsing:
    def test_detects_oom(self):
        logs = "2024-01-01 container=web OOMKilled\nsome other line\n"
        errors = parse_logs(logs, ["web", "postgres"])
        assert len(errors) == 1
        assert errors[0].kind == "oom"
        assert errors[0].component == "web"

    def test_detects_crashloop(self):
        logs = "pod/web-abc123 CrashLoopBackOff\n"
        errors = parse_logs(logs, ["web"])
        assert len(errors) == 1
        assert errors[0].kind == "crashloop"

    def test_detects_image_pull(self):
        logs = "Failed to pull image: ImagePullBackOff for container web\n"
        errors = parse_logs(logs, ["web"])
        assert len(errors) == 1
        assert errors[0].kind == "image_pull"

    def test_detects_build_error(self):
        logs = "COPY failed: file not found in build context\n"
        errors = parse_logs(logs, ["web"])
        assert len(errors) == 1
        assert errors[0].kind == "build"

    def test_no_errors_in_clean_logs(self):
        logs = "Starting web server on port 8000\nReady to accept connections\n"
        errors = parse_logs(logs, ["web"])
        assert len(errors) == 0

    def test_deduplicates_same_kind_component(self):
        logs = "container=web OOMKilled\ncontainer=web OOMKilled again\n"
        errors = parse_logs(logs, ["web"])
        assert len(errors) == 1

    def test_multiple_different_errors(self):
        logs = "container=web OOMKilled\ncontainer=postgres CrashLoopBackOff\n"
        errors = parse_logs(logs, ["web", "postgres"])
        assert len(errors) == 2
        kinds = {e.kind for e in errors}
        assert "oom" in kinds
        assert "crashloop" in kinds


# ---------------------------------------------------------------------------
# Deterministic patching
# ---------------------------------------------------------------------------


class TestDeterministicFix:
    @pytest.mark.parametrize("force", [False, True])
    def test_fix_respects_existing_and_edited_files(self, tmp_path, force):
        model = _make_model()
        state = StateManager(tmp_path)
        state.init_state_dir()
        state.write_infra_model(model)
        compose = tmp_path / "docker-compose.yml"
        compose.write_text("# original compose\n")
        Generator(tmp_path).generate(model, target="k8s")
        deployment = tmp_path / "k8s/web-deployment.yaml"
        deployment.write_text("# edited deployment\n")
        logs = tmp_path / "build.log"
        logs.write_text("container=web OOMKilled\n")

        result = FixLoop(tmp_path).fix(logs, force=force)

        assert result["changes"]
        if force:
            assert result["status"] == "applied"
            assert state.read_infra_model().services[0].sizing.memory_limits == "1024Mi"
            assert str(compose) in result["files"]
            assert str(deployment) in result["files"]
            assert "1024Mi" in deployment.read_text()
            assert result["skipped"] == []
        else:
            assert result["status"] == "blocked"
            assert state.read_infra_model() == model
            assert result["files"] == []
            assert compose.read_text() == "# original compose\n"
            assert deployment.read_text() == "# edited deployment\n"
            assert {str(compose), str(deployment)} <= set(result["skipped"])
            assert not state.is_tracked(compose.name)
            retry = FixLoop(tmp_path).fix(logs)
            assert retry["status"] == "blocked"
            assert retry["changes"] == result["changes"]
            assert state.read_infra_model() == model
            applied = FixLoop(tmp_path).fix(logs, force=True)
            assert applied["status"] == "applied"
            assert state.read_infra_model().services[0].sizing.memory_limits == "1024Mi"
            assert "1024Mi" in deployment.read_text()

    def test_oom_doubles_memory(self, tmp_path: Path):
        model = _make_model(memory_limits="512Mi")
        state = StateManager(tmp_path)
        state.init_state_dir()
        state.write_infra_model(model)

        log_file = tmp_path / "build.log"
        log_file.write_text("container=web OOMKilled\n", encoding="utf-8")

        loop = FixLoop(tmp_path)
        result = loop.fix(log_file)

        assert len(result["errors"]) == 1
        assert len(result["changes"]) > 0

        # Verify the patched model has doubled memory
        patched = state.read_infra_model()
        web = [s for s in patched.services if s.name == "web"][0]
        assert web.sizing.memory_limits == "1024Mi"

    def test_crashloop_adds_depends_on(self, tmp_path: Path):
        model = _make_model()
        state = StateManager(tmp_path)
        state.init_state_dir()
        state.write_infra_model(model)

        log_file = tmp_path / "build.log"
        log_file.write_text("pod/web-abc CrashLoopBackOff\n", encoding="utf-8")

        loop = FixLoop(tmp_path)
        result = loop.fix(log_file)

        assert len(result["errors"]) == 1
        # Web should now depend on postgres
        patched = state.read_infra_model()
        web = [s for s in patched.services if s.name == "web"][0]
        assert "postgres" in web.depends_on

    @pytest.mark.parametrize("existing_audit", [False, True])
    def test_dry_run_does_not_write(self, tmp_path: Path, existing_audit):
        model = _make_model(memory_limits="512Mi")
        state = StateManager(tmp_path)
        state.init_state_dir()
        state.write_infra_model(model)

        log_file = tmp_path / "build.log"
        log_file.write_text("container=web OOMKilled\n", encoding="utf-8")

        if existing_audit:
            state.write_atomic("logs/fix_errors.json", "previous audit")
            state.write_atomic("logs/fix_result.json", "previous result")
        before = _tree_snapshot(tmp_path)
        loop = FixLoop(tmp_path)
        result = loop.fix(log_file, dry_run=True)
        assert _tree_snapshot(tmp_path) == before
        assert result["status"] == "dry_run"

        assert len(result["changes"]) > 0
        assert len(result["files"]) == 0

        # Verify the model on disk is unchanged
        loaded = state.read_infra_model()
        web = [s for s in loaded.services if s.name == "web"][0]
        assert web.sizing.memory_limits == "512Mi"

    def test_no_errors_returns_empty(self, tmp_path: Path):
        model = _make_model()
        state = StateManager(tmp_path)
        state.init_state_dir()
        state.write_infra_model(model)

        log_file = tmp_path / "build.log"
        log_file.write_text("Everything is fine\n", encoding="utf-8")

        loop = FixLoop(tmp_path)
        result = loop.fix(log_file)

        assert len(result["errors"]) == 0
        assert len(result["changes"]) == 0

    def test_fix_writes_audit_log(self, tmp_path: Path):
        model = _make_model(memory_limits="512Mi")
        state = StateManager(tmp_path)
        state.init_state_dir()
        state.write_infra_model(model)

        log_file = tmp_path / "build.log"
        log_file.write_text("container=web OOMKilled\n", encoding="utf-8")

        loop = FixLoop(tmp_path)
        loop.fix(log_file)

        # Audit logs should be written
        errors_log = tmp_path / ".ai-infra" / "logs" / "fix_errors.json"
        assert errors_log.exists()
        result_log = tmp_path / ".ai-infra" / "logs" / "fix_result.json"
        assert result_log.exists()


def _tree_snapshot(root):
    return {
        path.relative_to(root).as_posix(): (
            path.read_bytes(), path.stat().st_mtime_ns
        ) if path.is_file() else None
        for path in root.rglob("*")
    }


def test_regeneration_failure_is_explicit_and_retry_uses_original_model(tmp_path, monkeypatch):
    model = _make_model()
    state = StateManager(tmp_path)
    state.init_state_dir()
    state.write_infra_model(model)
    Generator(tmp_path).generate(model, target="all")
    log = tmp_path / "crash.log"
    log.write_text("container=web OOMKilled\ncontainer=postgres OOMKilled\n")
    original = Path.write_text

    def fail_second_deployment(path, *args, **kwargs):
        if path.name == "postgres-deployment.yaml":
            raise OSError("simulated write failure")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "write_text", fail_second_deployment)
        failed = FixLoop(tmp_path).fix(log)
    assert failed["status"] == "partial"
    assert state.read_infra_model() == model
    deployment = tmp_path / "k8s/web-deployment.yaml"
    assert str(deployment) in failed["files"]
    assert "1024Mi" in deployment.read_text()
    retry = FixLoop(tmp_path).fix(log)
    assert retry["status"] == "applied"
    assert retry["changes"] == failed["changes"]
    assert state.read_infra_model().services[0].sizing.memory_limits == "1024Mi"


def test_fix_keeps_existing_dockerignore_even_with_force(tmp_path):
    state = StateManager(tmp_path)
    state.init_state_dir()
    state.write_infra_model(_make_model())
    ignore = tmp_path / ".dockerignore"
    ignore.write_text("private-config/\n")
    log = tmp_path / "crash.log"
    log.write_text("container=web OOMKilled\n")
    result = FixLoop(tmp_path).fix(log, force=True)
    assert result["status"] == "applied"
    assert str(ignore) in result["skipped"]
    assert ignore.read_text() == "private-config/\n"
