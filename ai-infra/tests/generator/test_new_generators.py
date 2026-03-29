"""Tests for new generator targets: Helm, IaC, monitoring, tenancy, multi-CI."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_infra.generator.generator import Generator
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
    VolumeMount,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _enterprise_model(**overrides) -> InfraModel:
    """Build a model with all enterprise features enabled."""
    defaults = dict(
        project_name="enterprise-app",
        routing=RoutingModel(domain="app.example.com"),
        services=[
            ServiceModel(
                name="web",
                type="app",
                image="python:3.11-slim",
                entrypoint="uvicorn main:app --host 0.0.0.0 --port 8000",
                ports=[PortMapping(container=8000, host=8000)],
                depends_on=["postgres"],
                env={
                    "DATABASE_URL": LiteralEnv(value="postgres://u:p@postgres:5432/db"),
                },
                sizing=SizingModel(scale="prod", replicas=2),
            ),
            ServiceModel(
                name="postgres",
                type="database",
                image="postgres:16-alpine",
                ports=[PortMapping(container=5432, host=5432)],
                env={"POSTGRES_PASSWORD": SecretEnv(ref="POSTGRES_PASSWORD")},
                sizing=SizingModel(scale="prod"),
                volumes=[VolumeMount(name="pgdata", mount_path="/var/lib/postgresql/data")],
            ),
        ],
        helm=HelmModel(enabled=True, chart_name="enterprise-app"),
        iac=IaCModel(enabled=True, cloud_provider="aws", region="us-west-2"),
        cicd=CICDModel(providers=["github_actions", "gitlab_ci", "bitbucket_pipelines", "circleci"]),
        monitoring=MonitoringModel(enabled=True),
        multi_tenancy=MultiTenancyModel(
            enabled=True,
            tenants=[TenantModel(name="acme"), TenantModel(name="globex")],
        ),
    )
    defaults.update(overrides)
    return InfraModel(**defaults)


# ---------------------------------------------------------------------------
# Helm
# ---------------------------------------------------------------------------


class TestHelmGeneration:
    def test_generates_chart_yaml(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        files = gen.generate(model, target="helm")
        names = [f.name for f in files]
        assert "Chart.yaml" in names

    def test_generates_values_yaml(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        files = gen.generate(model, target="helm")
        names = [f.name for f in files]
        assert "values.yaml" in names

    def test_generates_helm_templates(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        files = gen.generate(model, target="helm")
        names = [f.name for f in files]
        assert "deployment.yaml" in names
        assert "service.yaml" in names
        assert "ingress.yaml" in names

    def test_chart_yaml_content(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        gen.generate(model, target="helm")
        content = (tmp_path / "helm" / "enterprise-app" / "Chart.yaml").read_text()
        assert "enterprise-app" in content
        assert "0.1.0" in content

    def test_values_yaml_content(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        gen.generate(model, target="helm")
        content = (tmp_path / "helm" / "enterprise-app" / "values.yaml").read_text()
        assert "web:" in content
        assert "postgres:" in content

    def test_helm_skipped_when_disabled(self, tmp_path: Path):
        model = _enterprise_model(helm=HelmModel(enabled=False))
        gen = Generator(tmp_path)
        files = gen.generate(model, target="helm")
        assert len(files) == 0


# ---------------------------------------------------------------------------
# IaC / Terraform
# ---------------------------------------------------------------------------


class TestIaCGeneration:
    def test_generates_aws_terraform(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        files = gen.generate(model, target="iac")
        names = [f.name for f in files]
        assert "main.tf" in names

    def test_aws_terraform_content(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        gen.generate(model, target="iac")
        content = (tmp_path / "terraform" / "main.tf").read_text()
        assert "aws" in content
        assert "eks" in content.lower()
        assert "us-west-2" in content

    def test_gcp_terraform(self, tmp_path: Path):
        model = _enterprise_model(
            iac=IaCModel(enabled=True, cloud_provider="gcp", region="us-central1"),
        )
        gen = Generator(tmp_path)
        gen.generate(model, target="iac")
        content = (tmp_path / "terraform" / "main.tf").read_text()
        assert "google" in content
        assert "gke" in content.lower() or "container_cluster" in content

    def test_azure_terraform(self, tmp_path: Path):
        model = _enterprise_model(
            iac=IaCModel(enabled=True, cloud_provider="azure", region="eastus"),
        )
        gen = Generator(tmp_path)
        gen.generate(model, target="iac")
        content = (tmp_path / "terraform" / "main.tf").read_text()
        assert "azurerm" in content
        assert "aks" in content.lower() or "kubernetes_cluster" in content

    def test_iac_skipped_when_disabled(self, tmp_path: Path):
        model = _enterprise_model(iac=IaCModel(enabled=False))
        gen = Generator(tmp_path)
        files = gen.generate(model, target="iac")
        assert len(files) == 0


# ---------------------------------------------------------------------------
# Multi CI/CD
# ---------------------------------------------------------------------------


class TestMultiCIGeneration:
    def test_github_actions_generated(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        files = gen.generate(model, target="ci")
        paths = [str(f.relative_to(tmp_path)) for f in files]
        assert any("deploy.yml" in p for p in paths)

    def test_gitlab_ci_generated(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        files = gen.generate(model, target="ci")
        names = [f.name for f in files]
        assert ".gitlab-ci.yml" in names

    def test_bitbucket_pipelines_generated(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        files = gen.generate(model, target="ci")
        names = [f.name for f in files]
        assert "bitbucket-pipelines.yml" in names

    def test_circleci_generated(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        files = gen.generate(model, target="ci")
        paths = [str(f.relative_to(tmp_path)) for f in files]
        assert any("config.yml" in p for p in paths)

    def test_gitlab_ci_content(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        gen.generate(model, target="ci")
        content = (tmp_path / ".gitlab-ci.yml").read_text()
        assert "stages:" in content
        assert "build" in content
        assert "web" in content


# ---------------------------------------------------------------------------
# Monitoring
# ---------------------------------------------------------------------------


class TestMonitoringGeneration:
    def test_generates_servicemonitor(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        files = gen.generate(model, target="monitoring")
        names = [f.name for f in files]
        assert "web-servicemonitor.yaml" in names

    def test_generates_alerting_rules(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        files = gen.generate(model, target="monitoring")
        names = [f.name for f in files]
        assert "alerting-rules.yaml" in names

    def test_generates_grafana_dashboard(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        files = gen.generate(model, target="monitoring")
        names = [f.name for f in files]
        assert "grafana-dashboard.json" in names

    def test_servicemonitor_content(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        gen.generate(model, target="monitoring")
        content = (tmp_path / "monitoring" / "web-servicemonitor.yaml").read_text()
        assert "ServiceMonitor" in content
        assert "web" in content

    def test_alerting_rules_content(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        gen.generate(model, target="monitoring")
        content = (tmp_path / "monitoring" / "alerting-rules.yaml").read_text()
        assert "PrometheusRule" in content
        assert "HighCpuUsage" in content

    def test_grafana_dashboard_content(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        gen.generate(model, target="monitoring")
        content = (tmp_path / "monitoring" / "grafana-dashboard.json").read_text()
        assert "enterprise-app" in content
        assert "timeseries" in content

    def test_monitoring_skipped_when_disabled(self, tmp_path: Path):
        model = _enterprise_model(monitoring=MonitoringModel(enabled=False))
        gen = Generator(tmp_path)
        files = gen.generate(model, target="monitoring")
        assert len(files) == 0


# ---------------------------------------------------------------------------
# Multi-tenancy
# ---------------------------------------------------------------------------


class TestTenancyGeneration:
    def test_generates_namespace_per_tenant(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        files = gen.generate(model, target="tenancy")
        names = [f.name for f in files]
        assert names.count("namespace.yaml") == 2

    def test_generates_resource_quota_per_tenant(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        files = gen.generate(model, target="tenancy")
        names = [f.name for f in files]
        assert names.count("resource-quota.yaml") == 2

    def test_generates_network_policy_per_tenant(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        files = gen.generate(model, target="tenancy")
        names = [f.name for f in files]
        assert names.count("network-policy.yaml") == 2

    def test_namespace_content(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        gen.generate(model, target="tenancy")
        content = (tmp_path / "k8s" / "tenants" / "acme" / "namespace.yaml").read_text()
        assert "Namespace" in content
        assert "acme" in content

    def test_resource_quota_content(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        gen.generate(model, target="tenancy")
        content = (tmp_path / "k8s" / "tenants" / "acme" / "resource-quota.yaml").read_text()
        assert "ResourceQuota" in content
        assert "4" in content  # default CPU quota

    def test_network_policy_content(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        gen.generate(model, target="tenancy")
        content = (tmp_path / "k8s" / "tenants" / "acme" / "network-policy.yaml").read_text()
        assert "NetworkPolicy" in content
        assert "acme" in content

    def test_tenancy_skipped_when_disabled(self, tmp_path: Path):
        model = _enterprise_model(multi_tenancy=MultiTenancyModel(enabled=False))
        gen = Generator(tmp_path)
        files = gen.generate(model, target="tenancy")
        assert len(files) == 0


# ---------------------------------------------------------------------------
# All target with enterprise features
# ---------------------------------------------------------------------------


class TestAllWithEnterprise:
    def test_all_generates_enterprise_features(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        files = gen.generate(model, target="all")
        names = [f.name for f in files]
        # Core
        assert "docker-compose.yml" in names
        assert "Dockerfile.web" in names
        # K8s
        assert "web-deployment.yaml" in names
        # CI
        assert ".gitlab-ci.yml" in names
        # Helm
        assert "Chart.yaml" in names
        assert "values.yaml" in names
        # IaC
        assert "main.tf" in names
        # Monitoring
        assert "web-servicemonitor.yaml" in names
        assert "alerting-rules.yaml" in names
        assert "grafana-dashboard.json" in names
        # Tenancy
        assert "namespace.yaml" in names
