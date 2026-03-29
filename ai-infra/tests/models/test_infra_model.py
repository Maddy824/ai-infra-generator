"""Tests for the InfraModel Pydantic v2 schema."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_model(**overrides) -> InfraModel:
    defaults = dict(
        project_name="test",
        routing=RoutingModel(domain="localhost"),
        services=[
            ServiceModel(
                name="web",
                type="app",
                image="python:3.11-slim",
                ports=[PortMapping(container=8000, host=8000)],
                sizing=SizingModel(),
            ),
        ],
    )
    defaults.update(overrides)
    return InfraModel(**defaults)


# ---------------------------------------------------------------------------
# Frozen / immutability
# ---------------------------------------------------------------------------


class TestFrozen:
    def test_model_is_frozen(self):
        model = _minimal_model()
        with pytest.raises(ValidationError):
            model.project_name = "changed"

    def test_service_is_frozen(self):
        model = _minimal_model()
        with pytest.raises(ValidationError):
            model.services[0].name = "changed"


# ---------------------------------------------------------------------------
# Round-trip serialization
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_json_round_trip(self, sample_model):
        json_str = sample_model.model_dump_json(indent=2)
        restored = InfraModel.model_validate_json(json_str)
        assert restored.model_dump() == sample_model.model_dump()

    def test_dict_round_trip(self, sample_model):
        data = sample_model.model_dump()
        restored = InfraModel.model_validate(data)
        assert restored.model_dump() == data


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_missing_project_name(self):
        with pytest.raises(ValidationError):
            InfraModel(
                routing=RoutingModel(domain="localhost"),
                services=[
                    ServiceModel(name="web", type="app", image="python:3.11-slim"),
                ],
            )

    def test_empty_services_rejected(self):
        with pytest.raises(ValidationError):
            InfraModel(
                project_name="test",
                routing=RoutingModel(domain="localhost"),
                services=[],
            )

    def test_invalid_port(self):
        with pytest.raises(ValidationError):
            PortMapping(container=0, host=8000)

    def test_invalid_port_high(self):
        with pytest.raises(ValidationError):
            PortMapping(container=70000, host=8000)

    def test_empty_service_name(self):
        with pytest.raises(ValidationError):
            ServiceModel(name="", type="app", image="python:3.11-slim")

    def test_invalid_service_type(self):
        with pytest.raises(ValidationError):
            ServiceModel(name="web", type="invalid", image="python:3.11-slim")


# ---------------------------------------------------------------------------
# Env var discriminated union
# ---------------------------------------------------------------------------


class TestEnvVars:
    def test_literal_env(self):
        env = LiteralEnv(value="hello")
        assert env.kind == "literal"
        assert env.value == "hello"

    def test_ref_env(self):
        env = RefEnv(ref="MY_VAR")
        assert env.kind == "ref"
        assert env.ref == "MY_VAR"

    def test_secret_env(self):
        env = SecretEnv(ref="MY_SECRET")
        assert env.kind == "secret"
        assert env.ref == "MY_SECRET"

    def test_env_in_service(self, sample_model):
        web = sample_model.services[0]
        assert web.env["DATABASE_URL"].kind == "literal"
        assert web.env["API_KEY"].kind == "ref"
        assert web.env["SECRET_TOKEN"].kind == "secret"


# ---------------------------------------------------------------------------
# New sub-model defaults
# ---------------------------------------------------------------------------


class TestNewSubModelDefaults:
    def test_helm_defaults(self):
        model = _minimal_model()
        assert model.helm.enabled is False
        assert model.helm.chart_version == "0.1.0"

    def test_iac_defaults(self):
        model = _minimal_model()
        assert model.iac.enabled is False
        assert model.iac.tool == "terraform"
        assert model.iac.cloud_provider == "aws"

    def test_cicd_defaults(self):
        model = _minimal_model()
        assert model.cicd.providers == ["github_actions"]
        assert model.cicd.registry == "ghcr.io"

    def test_monitoring_defaults(self):
        model = _minimal_model()
        assert model.monitoring.enabled is False
        assert model.monitoring.prometheus is True
        assert model.monitoring.grafana is True

    def test_tenancy_defaults(self):
        model = _minimal_model()
        assert model.multi_tenancy.enabled is False
        assert model.multi_tenancy.tenants == []

    def test_tenant_defaults(self):
        t = TenantModel(name="acme")
        assert t.namespace is None
        assert t.resource_quota_cpu == "4"
        assert t.resource_quota_memory == "8Gi"


# ---------------------------------------------------------------------------
# New sub-model validation
# ---------------------------------------------------------------------------


class TestNewSubModelValidation:
    def test_invalid_iac_tool(self):
        with pytest.raises(ValidationError):
            IaCModel(enabled=True, tool="ansible")

    def test_invalid_iac_cloud_provider(self):
        with pytest.raises(ValidationError):
            IaCModel(enabled=True, cloud_provider="oracle")

    def test_iac_node_count_below_one(self):
        with pytest.raises(ValidationError):
            IaCModel(enabled=True, node_count=0)

    def test_invalid_cicd_provider(self):
        with pytest.raises(ValidationError):
            CICDModel(providers=["jenkins"])

    def test_invalid_cluster_auth(self):
        with pytest.raises(ValidationError):
            CICDModel(cluster_auth="digitalocean")

    def test_monitoring_invalid_metrics_port(self):
        with pytest.raises(ValidationError):
            MonitoringModel(enabled=True, metrics_port=0)

    def test_monitoring_metrics_port_too_high(self):
        with pytest.raises(ValidationError):
            MonitoringModel(enabled=True, metrics_port=70000)

    def test_invalid_isolation_level(self):
        with pytest.raises(ValidationError):
            MultiTenancyModel(enabled=True, isolation_level="vcluster")

    def test_tenant_empty_name(self):
        with pytest.raises(ValidationError):
            TenantModel(name="")


# ---------------------------------------------------------------------------
# Round-trip with all new fields populated
# ---------------------------------------------------------------------------


class TestNewSubModelRoundTrip:
    def test_round_trip_with_all_new_fields(self):
        model = _minimal_model(
            helm=HelmModel(enabled=True, chart_name="my-chart"),
            iac=IaCModel(enabled=True, cloud_provider="gcp", region="us-central1"),
            cicd=CICDModel(providers=["github_actions", "gitlab_ci"]),
            monitoring=MonitoringModel(enabled=True, metrics_port=8080),
            multi_tenancy=MultiTenancyModel(
                enabled=True,
                tenants=[TenantModel(name="acme"), TenantModel(name="globex")],
            ),
        )
        json_str = model.model_dump_json(indent=2)
        restored = InfraModel.model_validate_json(json_str)
        assert restored.helm.enabled is True
        assert restored.helm.chart_name == "my-chart"
        assert restored.iac.cloud_provider == "gcp"
        assert "gitlab_ci" in restored.cicd.providers
        assert restored.monitoring.metrics_port == 8080
        assert len(restored.multi_tenancy.tenants) == 2


# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------


class TestSchemaVersion:
    def test_default_version(self):
        model = _minimal_model()
        assert model.version == "1.0"

    def test_version_preserved_on_round_trip(self):
        model = _minimal_model()
        data = model.model_dump()
        assert data["version"] == "1.0"
        restored = InfraModel.model_validate(data)
        assert restored.version == "1.0"
