"""Golden snapshot tests for new generator paths.

These tests generate output from a canonical InfraModel and compare it
byte-for-byte against checked-in golden files to detect regressions.

To update golden files after an intentional template change, run:
    python -m pytest tests/generator/test_golden_snapshots.py --update-golden

Or delete the old golden files and re-run the generation script.
"""

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

_GOLDEN_DIR = Path(__file__).parent.parent / "golden" / "enterprise_stack"


def _enterprise_model() -> InfraModel:
    """The canonical enterprise model used to generate golden snapshots."""
    return InfraModel(
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
                env={"DATABASE_URL": LiteralEnv(value="postgres://u:p@postgres:5432/db")},
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
        cicd=CICDModel(providers=["github_actions", "gitlab_ci"]),
        monitoring=MonitoringModel(enabled=True),
        multi_tenancy=MultiTenancyModel(
            enabled=True,
            tenants=[TenantModel(name="acme"), TenantModel(name="globex")],
        ),
    )


def _assert_matches_golden(generated_path: Path, golden_name: str) -> None:
    """Assert that a generated file matches its golden snapshot."""
    golden_path = _GOLDEN_DIR / golden_name
    assert golden_path.exists(), f"Golden file missing: {golden_path}"

    generated = generated_path.read_text(encoding="utf-8")
    expected = golden_path.read_text(encoding="utf-8")

    assert generated == expected, (
        f"Generated output does not match golden snapshot.\n"
        f"  Generated: {generated_path}\n"
        f"  Golden:    {golden_path}\n"
        f"Run the golden snapshot generation script to update."
    )


# ---------------------------------------------------------------------------
# Helm chart snapshots
# ---------------------------------------------------------------------------


class TestHelmGolden:
    def test_chart_yaml(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        gen.generate(model, target="helm")
        _assert_matches_golden(
            tmp_path / "helm" / "enterprise-app" / "Chart.yaml",
            "Chart.yaml",
        )

    def test_values_yaml(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        gen.generate(model, target="helm")
        _assert_matches_golden(
            tmp_path / "helm" / "enterprise-app" / "values.yaml",
            "values.yaml",
        )


# ---------------------------------------------------------------------------
# Terraform IaC snapshot
# ---------------------------------------------------------------------------


class TestIaCGolden:
    def test_aws_main_tf(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        gen.generate(model, target="iac")
        _assert_matches_golden(
            tmp_path / "terraform" / "main.tf",
            "main.tf",
        )


# ---------------------------------------------------------------------------
# Monitoring snapshots
# ---------------------------------------------------------------------------


class TestMonitoringGolden:
    def test_servicemonitor(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        gen.generate(model, target="monitoring")
        _assert_matches_golden(
            tmp_path / "monitoring" / "web-servicemonitor.yaml",
            "web-servicemonitor.yaml",
        )

    def test_alerting_rules(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        gen.generate(model, target="monitoring")
        _assert_matches_golden(
            tmp_path / "monitoring" / "alerting-rules.yaml",
            "alerting-rules.yaml",
        )

    def test_grafana_dashboard(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        gen.generate(model, target="monitoring")
        _assert_matches_golden(
            tmp_path / "monitoring" / "grafana-dashboard.json",
            "grafana-dashboard.json",
        )


# ---------------------------------------------------------------------------
# Tenancy snapshots
# ---------------------------------------------------------------------------


class TestTenancyGolden:
    def test_namespace(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        gen.generate(model, target="tenancy")
        _assert_matches_golden(
            tmp_path / "k8s" / "tenants" / "acme" / "namespace.yaml",
            "acme-namespace.yaml",
        )

    def test_resource_quota(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        gen.generate(model, target="tenancy")
        _assert_matches_golden(
            tmp_path / "k8s" / "tenants" / "acme" / "resource-quota.yaml",
            "acme-resource-quota.yaml",
        )

    def test_network_policy(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        gen.generate(model, target="tenancy")
        _assert_matches_golden(
            tmp_path / "k8s" / "tenants" / "acme" / "network-policy.yaml",
            "acme-network-policy.yaml",
        )


# ---------------------------------------------------------------------------
# CI snapshot
# ---------------------------------------------------------------------------


class TestCIGolden:
    def test_gitlab_ci(self, tmp_path: Path):
        model = _enterprise_model()
        gen = Generator(tmp_path)
        gen.generate(model, target="ci")
        _assert_matches_golden(
            tmp_path / ".gitlab-ci.yml",
            "gitlab-ci.yml",
        )
