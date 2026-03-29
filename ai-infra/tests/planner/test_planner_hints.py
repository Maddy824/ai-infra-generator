"""Tests that canned analyzer_output + hints produce expected InfraModel fields.

Each test monkeypatches the LLM to return a model whose fields reflect what
the hints requested, then asserts the planner round-trip preserves those fields
through Pydantic validation and atomic state writes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_infra.models.infra_model import (
    CICDModel,
    HelmModel,
    IaCModel,
    InfraModel,
    LiteralEnv,
    MonitoringModel,
    MultiTenancyModel,
    PortMapping,
    RoutingModel,
    SecretEnv,
    ServiceModel,
    SizingModel,
    TenantModel,
)
from ai_infra.planner.planner import Planner
from ai_infra.state.state_manager import StateManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_ANALYZER = {
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


def _base_model(**overrides) -> InfraModel:
    """Build a minimal model, then apply overrides."""
    defaults = dict(
        project_name="test-project",
        routing=RoutingModel(domain="localhost"),
        services=[
            ServiceModel(
                name="web",
                type="app",
                image="python:3.11-slim",
                entrypoint="uvicorn main:app --host 0.0.0.0 --port 8000",
                ports=[PortMapping(container=8000, host=8000)],
                depends_on=["postgres"],
                env={"DATABASE_URL": LiteralEnv(value="postgres://u:p@postgres:5432/db")},
                sizing=SizingModel(scale="dev"),
            ),
            ServiceModel(
                name="postgres",
                type="database",
                image="postgres:16-alpine",
                ports=[PortMapping(container=5432, host=5432)],
                env={"POSTGRES_PASSWORD": SecretEnv(ref="POSTGRES_PASSWORD")},
                sizing=SizingModel(scale="dev"),
            ),
        ],
    )
    defaults.update(overrides)
    return InfraModel(**defaults)


def _mock_llm_returning(model: InfraModel, monkeypatch):
    """Patch Planner._call_llm to return *model* as JSON."""
    model_json = model.model_dump_json(indent=2)

    def _fake(self, system: str, user: str) -> str:
        return model_json

    monkeypatch.setattr("ai_infra.planner.planner.Planner._call_llm", _fake)


def _run_planner(tmp_repo_with_state: Path, hints_yaml: str = "") -> InfraModel:
    """Run the planner with optional hints and return the result."""
    state = StateManager(tmp_repo_with_state)
    state.write_analyzer_output(_BASE_ANALYZER)
    if hints_yaml:
        state.write_atomic("hints.yaml", hints_yaml)
    planner = Planner(tmp_repo_with_state)
    return planner.plan(_BASE_ANALYZER)


# ---------------------------------------------------------------------------
# Conservative defaults (no hints -> enterprise features disabled)
# ---------------------------------------------------------------------------


class TestConservativeDefaults:
    """When no hints are given, enterprise features stay disabled."""

    def test_defaults_helm_disabled(self, tmp_repo_with_state: Path, monkeypatch):
        _mock_llm_returning(_base_model(), monkeypatch)
        model = _run_planner(tmp_repo_with_state)
        assert model.helm.enabled is False

    def test_defaults_iac_disabled(self, tmp_repo_with_state: Path, monkeypatch):
        _mock_llm_returning(_base_model(), monkeypatch)
        model = _run_planner(tmp_repo_with_state)
        assert model.iac.enabled is False

    def test_defaults_monitoring_disabled(self, tmp_repo_with_state: Path, monkeypatch):
        _mock_llm_returning(_base_model(), monkeypatch)
        model = _run_planner(tmp_repo_with_state)
        assert model.monitoring.enabled is False

    def test_defaults_tenancy_disabled(self, tmp_repo_with_state: Path, monkeypatch):
        _mock_llm_returning(_base_model(), monkeypatch)
        model = _run_planner(tmp_repo_with_state)
        assert model.multi_tenancy.enabled is False

    def test_defaults_cicd_github_only(self, tmp_repo_with_state: Path, monkeypatch):
        _mock_llm_returning(_base_model(), monkeypatch)
        model = _run_planner(tmp_repo_with_state)
        assert model.cicd.providers == ["github_actions"]


# ---------------------------------------------------------------------------
# Hints -> Helm enabled
# ---------------------------------------------------------------------------


class TestHintsEnableHelm:
    def test_helm_enabled_when_hinted(self, tmp_repo_with_state: Path, monkeypatch):
        expected = _base_model(helm=HelmModel(enabled=True, chart_name="my-app"))
        _mock_llm_returning(expected, monkeypatch)
        model = _run_planner(tmp_repo_with_state, "helm: true\n")
        assert model.helm.enabled is True
        assert model.helm.chart_name == "my-app"

    def test_helm_persisted_atomically(self, tmp_repo_with_state: Path, monkeypatch):
        expected = _base_model(helm=HelmModel(enabled=True))
        _mock_llm_returning(expected, monkeypatch)
        _run_planner(tmp_repo_with_state, "helm: true\n")
        loaded = StateManager(tmp_repo_with_state).read_infra_model()
        assert loaded.helm.enabled is True


# ---------------------------------------------------------------------------
# Hints -> IaC enabled
# ---------------------------------------------------------------------------


class TestHintsEnableIaC:
    def test_iac_aws_when_hinted(self, tmp_repo_with_state: Path, monkeypatch):
        expected = _base_model(
            iac=IaCModel(enabled=True, cloud_provider="aws", region="us-west-2"),
        )
        _mock_llm_returning(expected, monkeypatch)
        model = _run_planner(
            tmp_repo_with_state, "cloud_provider: aws\nregion: us-west-2\n"
        )
        assert model.iac.enabled is True
        assert model.iac.cloud_provider == "aws"
        assert model.iac.region == "us-west-2"

    def test_iac_gcp_when_hinted(self, tmp_repo_with_state: Path, monkeypatch):
        expected = _base_model(
            iac=IaCModel(enabled=True, cloud_provider="gcp", region="us-central1"),
        )
        _mock_llm_returning(expected, monkeypatch)
        model = _run_planner(tmp_repo_with_state, "cloud_provider: gcp\n")
        assert model.iac.cloud_provider == "gcp"


# ---------------------------------------------------------------------------
# Hints -> Monitoring enabled
# ---------------------------------------------------------------------------


class TestHintsEnableMonitoring:
    def test_monitoring_enabled_when_hinted(self, tmp_repo_with_state: Path, monkeypatch):
        expected = _base_model(monitoring=MonitoringModel(enabled=True))
        _mock_llm_returning(expected, monkeypatch)
        model = _run_planner(tmp_repo_with_state, "monitoring: true\n")
        assert model.monitoring.enabled is True
        assert model.monitoring.prometheus is True
        assert model.monitoring.grafana is True

    def test_monitoring_custom_port(self, tmp_repo_with_state: Path, monkeypatch):
        expected = _base_model(
            monitoring=MonitoringModel(enabled=True, metrics_port=8080),
        )
        _mock_llm_returning(expected, monkeypatch)
        model = _run_planner(tmp_repo_with_state, "monitoring: true\nmetrics_port: 8080\n")
        assert model.monitoring.metrics_port == 8080


# ---------------------------------------------------------------------------
# Hints -> Multi-tenancy enabled
# ---------------------------------------------------------------------------


class TestHintsEnableMultiTenancy:
    def test_tenancy_with_tenants(self, tmp_repo_with_state: Path, monkeypatch):
        expected = _base_model(
            multi_tenancy=MultiTenancyModel(
                enabled=True,
                tenants=[TenantModel(name="acme"), TenantModel(name="globex")],
            ),
        )
        _mock_llm_returning(expected, monkeypatch)
        model = _run_planner(tmp_repo_with_state, "multi_tenant: true\n")
        assert model.multi_tenancy.enabled is True
        assert len(model.multi_tenancy.tenants) == 2
        assert model.multi_tenancy.tenants[0].name == "acme"


# ---------------------------------------------------------------------------
# Hints -> Multi-CI/CD
# ---------------------------------------------------------------------------


class TestHintsMultiCI:
    def test_multiple_ci_providers(self, tmp_repo_with_state: Path, monkeypatch):
        expected = _base_model(
            cicd=CICDModel(providers=["github_actions", "gitlab_ci"]),
        )
        _mock_llm_returning(expected, monkeypatch)
        model = _run_planner(tmp_repo_with_state, "ci_cd: gitlab_ci\n")
        assert "gitlab_ci" in model.cicd.providers
        assert "github_actions" in model.cicd.providers


# ---------------------------------------------------------------------------
# Planner failure leaves state intact
# ---------------------------------------------------------------------------


class TestPlannerFailureInvariant:
    """On LLM failure, previous infra_model.v1.json must be untouched."""

    def test_failed_plan_preserves_existing_model(
        self, tmp_repo_with_state: Path, monkeypatch
    ):
        # Write a known-good model to state first
        state = StateManager(tmp_repo_with_state)
        state.write_analyzer_output(_BASE_ANALYZER)
        original = _base_model()
        state.write_infra_model(original)

        # Make the LLM always return garbage
        def _bad_llm(self, system: str, user: str) -> str:
            return '{"completely": "invalid"}'

        monkeypatch.setattr("ai_infra.planner.planner.Planner._call_llm", _bad_llm)

        planner = Planner(tmp_repo_with_state)
        with pytest.raises(RuntimeError, match="failed after"):
            planner.plan(_BASE_ANALYZER)

        # The original model must still be on disk, untouched
        loaded = state.read_infra_model()
        assert loaded.project_name == "test-project"
        assert loaded.model_dump() == original.model_dump()


# ---------------------------------------------------------------------------
# Plan summary includes new fields
# ---------------------------------------------------------------------------


class TestPlanSummaryNewFields:
    def test_summary_shows_cicd_providers(self, tmp_repo_with_state: Path, monkeypatch):
        expected = _base_model(
            cicd=CICDModel(providers=["github_actions", "gitlab_ci"]),
        )
        _mock_llm_returning(expected, monkeypatch)
        _run_planner(tmp_repo_with_state)
        summary = (tmp_repo_with_state / ".ai-infra" / "plan.md").read_text()
        assert "github_actions" in summary
        assert "gitlab_ci" in summary

    def test_summary_shows_helm_status(self, tmp_repo_with_state: Path, monkeypatch):
        expected = _base_model(helm=HelmModel(enabled=True, chart_name="my-chart"))
        _mock_llm_returning(expected, monkeypatch)
        _run_planner(tmp_repo_with_state)
        summary = (tmp_repo_with_state / ".ai-infra" / "plan.md").read_text()
        assert "Enabled" in summary
        assert "my-chart" in summary

    def test_summary_shows_disabled_features(self, tmp_repo_with_state: Path, monkeypatch):
        _mock_llm_returning(_base_model(), monkeypatch)
        _run_planner(tmp_repo_with_state)
        summary = (tmp_repo_with_state / ".ai-infra" / "plan.md").read_text()
        assert "Disabled" in summary
