"""Tests for the Generator module — core targets: compose, k8s, ci."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_infra.generator.generator import Generator
from ai_infra.models.infra_model import InfraModel


# ---------------------------------------------------------------------------
# Compose target
# ---------------------------------------------------------------------------


class TestComposeGeneration:
    def test_generates_dockerfiles(self, tmp_path: Path, sample_model: InfraModel):
        gen = Generator(tmp_path)
        files = gen.generate(sample_model, target="compose")
        # Should generate Dockerfile.web (not for database/cache) + docker-compose.yml
        names = [f.name for f in files]
        assert "Dockerfile.web" in names
        assert "docker-compose.yml" in names
        # No Dockerfile for database/cache services
        assert "Dockerfile.postgres" not in names
        assert "Dockerfile.redis" not in names

    def test_compose_contains_services(self, tmp_path: Path, sample_model: InfraModel):
        gen = Generator(tmp_path)
        gen.generate(sample_model, target="compose")
        content = (tmp_path / "docker-compose.yml").read_text()
        assert "web:" in content
        assert "postgres:" in content
        assert "redis:" in content

    def test_compose_port_mapping(self, tmp_path: Path, sample_model: InfraModel):
        gen = Generator(tmp_path)
        gen.generate(sample_model, target="compose")
        content = (tmp_path / "docker-compose.yml").read_text()
        assert "8000:8000" in content
        assert "5432:5432" in content

    def test_compose_depends_on(self, tmp_path: Path, sample_model: InfraModel):
        gen = Generator(tmp_path)
        gen.generate(sample_model, target="compose")
        content = (tmp_path / "docker-compose.yml").read_text()
        assert "depends_on:" in content

    def test_compose_volumes(self, tmp_path: Path, sample_model: InfraModel):
        gen = Generator(tmp_path)
        gen.generate(sample_model, target="compose")
        content = (tmp_path / "docker-compose.yml").read_text()
        assert "pgdata" in content


# ---------------------------------------------------------------------------
# K8s target
# ---------------------------------------------------------------------------


class TestK8sGeneration:
    def test_generates_deployment_per_service(self, tmp_path: Path, sample_model: InfraModel):
        gen = Generator(tmp_path)
        files = gen.generate(sample_model, target="k8s")
        names = [f.name for f in files]
        assert "web-deployment.yaml" in names
        assert "postgres-deployment.yaml" in names
        assert "redis-deployment.yaml" in names

    def test_generates_services(self, tmp_path: Path, sample_model: InfraModel):
        gen = Generator(tmp_path)
        files = gen.generate(sample_model, target="k8s")
        names = [f.name for f in files]
        assert "web-service.yaml" in names
        assert "postgres-service.yaml" in names

    def test_generates_ingress(self, tmp_path: Path, sample_model: InfraModel):
        gen = Generator(tmp_path)
        files = gen.generate(sample_model, target="k8s")
        names = [f.name for f in files]
        assert "ingress.yaml" in names

    def test_deployment_contains_resources(self, tmp_path: Path, sample_model: InfraModel):
        gen = Generator(tmp_path)
        gen.generate(sample_model, target="k8s")
        content = (tmp_path / "k8s" / "web-deployment.yaml").read_text()
        assert "cpu:" in content
        assert "memory:" in content

    def test_deployment_contains_env(self, tmp_path: Path, sample_model: InfraModel):
        gen = Generator(tmp_path)
        gen.generate(sample_model, target="k8s")
        content = (tmp_path / "k8s" / "web-deployment.yaml").read_text()
        assert "DATABASE_URL" in content

    def test_generates_secret(self, tmp_path: Path, sample_model: InfraModel):
        gen = Generator(tmp_path)
        files = gen.generate(sample_model, target="k8s")
        names = [f.name for f in files]
        assert "secret.yaml" in names

    def test_generates_configmap(self, tmp_path: Path, sample_model: InfraModel):
        gen = Generator(tmp_path)
        files = gen.generate(sample_model, target="k8s")
        names = [f.name for f in files]
        assert "configmap.yaml" in names

    def test_no_hpa_for_dev_scale(self, tmp_path: Path, sample_model: InfraModel):
        gen = Generator(tmp_path)
        files = gen.generate(sample_model, target="k8s")
        names = [f.name for f in files]
        assert "web-hpa.yaml" not in names

    def test_hpa_for_prod_scale(self, tmp_path: Path, sample_model_prod: InfraModel):
        gen = Generator(tmp_path)
        files = gen.generate(sample_model_prod, target="k8s")
        names = [f.name for f in files]
        assert "web-hpa.yaml" in names


# ---------------------------------------------------------------------------
# CI target
# ---------------------------------------------------------------------------


class TestCIGeneration:
    def test_generates_github_actions(self, tmp_path: Path, sample_model: InfraModel):
        gen = Generator(tmp_path)
        files = gen.generate(sample_model, target="ci")
        paths = [str(f.relative_to(tmp_path)) for f in files]
        assert any("deploy.yml" in p for p in paths)

    def test_github_actions_content(self, tmp_path: Path, sample_model: InfraModel):
        gen = Generator(tmp_path)
        gen.generate(sample_model, target="ci")
        content = (tmp_path / ".github" / "workflows" / "deploy.yml").read_text()
        assert "Build and Deploy" in content
        assert "web" in content


# ---------------------------------------------------------------------------
# All target
# ---------------------------------------------------------------------------


class TestAllTarget:
    def test_all_generates_everything(self, tmp_path: Path, sample_model: InfraModel):
        gen = Generator(tmp_path)
        files = gen.generate(sample_model, target="all")
        names = [f.name for f in files]
        # Should include compose + k8s + ci
        assert "docker-compose.yml" in names
        assert "Dockerfile.web" in names
        assert "web-deployment.yaml" in names
        assert "deploy.yml" in names
