from __future__ import annotations

import pytest
import yaml

from ai_infra.analyzer.core import analyze
from ai_infra.generator.generator import Generator
from ai_infra.models.infra_model import InfraModel
from ai_infra.planner.offline import build_offline_model
from ai_infra.planner.planner import Planner
from ai_infra.state.state_manager import StateManager


@pytest.mark.parametrize(("fixture", "image", "command", "port", "dependencies"), [
    ("fastapi_app_dir", "python:3.11-slim", "uvicorn main:app", 8000, ["postgres"]),
    ("django_app_dir", "python:3.11-slim", "python manage.py runserver", 8000, ["postgres", "redis"]),
    ("express_app_dir", "node:22-alpine", "node server.js", 3000, ["postgres", "redis"]),
    ("go_app_dir", "golang:1.21-alpine", "/server", 8080, ["redis"]),
])
def test_offline_plans_from_detector_fixtures(request, fixture, image, command, port, dependencies):
    repo = request.getfixturevalue(fixture)
    analysis = analyze(repo)
    model = build_offline_model(analysis)
    assert model == InfraModel.model_validate_json(model.model_dump_json())
    assert model.model_dump_json() == build_offline_model(analysis).model_dump_json()
    web = model.services[0]
    assert web.image == image
    assert web.entrypoint.startswith(command)
    assert web.ports[0].container == port
    assert web.depends_on == dependencies
    assert [service.name for service in model.services[1:]] == dependencies
    assert not model.cicd.auto_deploy
    assert not model.cicd.providers


def test_offline_persists_model_and_summary(tmp_repo_with_state, sample_analyzer_output, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("Offline planning must not call a backend")

    monkeypatch.setattr(Planner, "_call_llm", fail)
    # Offline planning must not read even a malformed hints file.
    StateManager(tmp_repo_with_state).write_atomic("hints.yaml", "invalid: [")
    model = Planner(tmp_repo_with_state).plan(sample_analyzer_output, offline=True)
    state = StateManager(tmp_repo_with_state)
    assert state.read_infra_model() == model
    assert model.project_name == "fastapi"
    assert "postgres" in state.read_file("plan.md")
    assert model.services[0].env["DATABASE_URL"].kind == "secret"


def test_offline_dependencies_stay_internal_and_app_binds_loopback(tmp_path):
    model = build_offline_model({
        "language": "python", "framework": "flask", "entrypoint": "app.py", "detected_port": 5432,
        "dependencies": {"inferred_services": ["redis", "mysql", "mongodb", "postgres", "s3", "worker"]},
    })
    assert [service.name for service in model.services] == ["web", "postgres", "mysql", "mongodb", "redis"]
    assert model.services[0].ports[0].host == 5432
    assert model.services[0].ports[0].host_ip == "127.0.0.1"
    assert all(service.ports[0].host is None for service in model.services[1:])
    Generator(tmp_path).generate(model, target="all")
    services = yaml.safe_load((tmp_path / "docker-compose.yml").read_text())["services"]
    assert services["web"]["ports"] == ["127.0.0.1:5432:5432"]
    for service in model.services[1:]:
        assert "ports" not in services[service.name]
        manifest = yaml.safe_load((tmp_path / "k8s" / f"{service.name}-service.yaml").read_text())
        assert manifest["spec"]["ports"][0]["port"] == service.ports[0].container
    assert model.services[1].ports[0].container == 5432
    assert model.services[1].env["POSTGRES_PASSWORD"].kind == "secret"
    assert all(service.volumes for service in model.services[1:])


def test_unknown_language_has_clear_error():
    with pytest.raises(RuntimeError, match="requires a detected"):
        build_offline_model({"language": None})


def test_invalid_detected_port_falls_back_to_framework_default():
    model = build_offline_model({"language": "python", "framework": "flask", "detected_port": 99999})
    assert model.services[0].ports[0].container == 5000


@pytest.mark.parametrize("name", ["2026", "true", "null", "yes", "on", "1e3"])
def test_offline_project_labels_are_strings(tmp_path, name):
    repo = tmp_path / name
    repo.mkdir()
    (repo / "requirements.txt").write_text("flask\npsycopg2-binary\n")
    model = build_offline_model(analyze(repo))
    assert model.project_name == name
    Generator(repo).generate(model, target="k8s")
    for path in (repo / "k8s").glob("*.yaml"):
        manifest = yaml.safe_load(path.read_text())
        assert manifest["metadata"]["labels"]["project"] == name
        if manifest["kind"] == "Deployment":
            assert manifest["spec"]["template"]["metadata"]["labels"]["project"] == name
