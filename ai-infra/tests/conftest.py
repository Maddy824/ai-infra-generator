"""Shared pytest fixtures for ai-infra tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_infra.models.infra_model import (
    CICDModel,
    ClusterAssumptionsModel,
    HelmModel,
    IaCModel,
    InfraModel,
    LiteralEnv,
    MonitoringModel,
    MultiTenancyModel,
    PortMapping,
    RefEnv,
    RoutingModel,
    SecretEnv,
    ServiceModel,
    SizingModel,
    TenantModel,
    VolumeMount,
)
from ai_infra.state.state_manager import StateManager


# ---------------------------------------------------------------------------
# Sample model builder
# ---------------------------------------------------------------------------


def _make_sample_model(*, scale: str = "dev") -> InfraModel:
    """Build a realistic sample InfraModel for testing."""
    return InfraModel(
        project_name="test-project",
        routing=RoutingModel(domain="localhost"),
        services=[
            ServiceModel(
                name="web",
                type="app",
                image="python:3.11-slim",
                entrypoint="uvicorn main:app --host 0.0.0.0 --port 8000",
                ports=[PortMapping(container=8000, host=8000)],
                depends_on=["postgres", "redis"],
                env={
                    "DATABASE_URL": LiteralEnv(value="postgres://user:pass@postgres:5432/db"),
                    "API_KEY": RefEnv(ref="API_KEY"),
                    "SECRET_TOKEN": SecretEnv(ref="SECRET_TOKEN"),
                },
                sizing=SizingModel(scale=scale),
            ),
            ServiceModel(
                name="postgres",
                type="database",
                image="postgres:16-alpine",
                ports=[PortMapping(container=5432, host=5432)],
                env={"POSTGRES_PASSWORD": SecretEnv(ref="POSTGRES_PASSWORD")},
                sizing=SizingModel(scale=scale),
                volumes=[VolumeMount(name="pgdata", mount_path="/var/lib/postgresql/data")],
            ),
            ServiceModel(
                name="redis",
                type="cache",
                image="redis:7-alpine",
                ports=[PortMapping(container=6379, host=6379)],
                sizing=SizingModel(scale=scale),
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_model() -> InfraModel:
    """A dev-scale sample InfraModel."""
    return _make_sample_model(scale="dev")


@pytest.fixture()
def sample_model_prod() -> InfraModel:
    """A prod-scale sample InfraModel."""
    return _make_sample_model(scale="prod")


@pytest.fixture()
def sample_analyzer_output() -> dict:
    """Canned analyzer output for planner tests."""
    return {
        "language": "python",
        "framework": "fastapi",
        "entrypoint": "main.py",
        "detected_port": 8000,
        "dependencies": {
            "raw": ["fastapi>=0.104", "uvicorn[standard]>=0.24", "psycopg2-binary>=2.9"],
            "inferred_services": ["postgres"],
        },
        "existing_infra_files": [],
    }


@pytest.fixture()
def tmp_repo_with_state(tmp_path: Path) -> Path:
    """Create a temp directory with an initialized .ai-infra/ state dir."""
    state = StateManager(tmp_path)
    state.init_state_dir()
    return tmp_path


@pytest.fixture()
def mock_llm_response(sample_model: InfraModel, monkeypatch) -> InfraModel:
    """Monkeypatch Planner._call_llm to return the sample model as JSON."""
    model_json = sample_model.model_dump_json(indent=2)

    def _fake_call_llm(self, system: str, user: str) -> str:
        return model_json

    monkeypatch.setattr(
        "ai_infra.planner.planner.Planner._call_llm",
        _fake_call_llm,
    )
    return sample_model


# ---------------------------------------------------------------------------
# Fixture directories for detector tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def fastapi_app_dir(tmp_path: Path) -> Path:
    """A minimal FastAPI app fixture."""
    (tmp_path / "main.py").write_text(
        'from fastapi import FastAPI\napp = FastAPI()\n\n@app.get("/")\ndef root():\n    return {"hello": "world"}\n',
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text(
        "fastapi>=0.104\nuvicorn[standard]>=0.24\npsycopg2-binary>=2.9\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def express_app_dir(tmp_path: Path) -> Path:
    """A minimal Express app fixture."""
    pkg = {
        "name": "express-app",
        "version": "1.0.0",
        "main": "server.js",
        "dependencies": {
            "express": "^4.18.2",
            "pg": "^8.11.3",
            "ioredis": "^5.3.2",
        },
    }
    (tmp_path / "package.json").write_text(json.dumps(pkg, indent=2), encoding="utf-8")
    (tmp_path / "server.js").write_text(
        'const express = require("express");\nconst app = express();\napp.listen(3000);\n',
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def django_app_dir(tmp_path: Path) -> Path:
    """A minimal Django app fixture."""
    (tmp_path / "manage.py").write_text(
        "#!/usr/bin/env python\nimport os, sys\nif __name__ == '__main__':\n    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myapp.settings')\n    from django.core.management import execute_from_command_line\n    execute_from_command_line(sys.argv)\n",
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text(
        "Django>=4.2\npsycopg2-binary>=2.9\ncelery>=5.3\nredis>=5.0\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def go_app_dir(tmp_path: Path) -> Path:
    """A minimal Go app fixture."""
    (tmp_path / "go.mod").write_text(
        "module github.com/example/myapp\n\ngo 1.21\n\nrequire (\n\tgithub.com/gin-gonic/gin v1.9.1\n\tgithub.com/go-redis/redis/v9 v9.3.0\n)\n",
        encoding="utf-8",
    )
    (tmp_path / "main.go").write_text(
        'package main\n\nimport "github.com/gin-gonic/gin"\n\nfunc main() {\n\tr := gin.Default()\n\tr.Run(":8080")\n}\n',
        encoding="utf-8",
    )
    return tmp_path
