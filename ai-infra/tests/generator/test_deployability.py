"""Tests that generated configs reference things that actually exist."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ai_infra.generator.generator import Generator, _runtime
from ai_infra.models.infra_model import (
    InfraModel,
    PortMapping,
    RoutingModel,
    ServiceModel,
)


def _two_app_model() -> InfraModel:
    return InfraModel(
        project_name="shop",
        routing=RoutingModel(domain="shop.example.com"),
        services=[
            ServiceModel(
                name="web", type="app", image="node:20-alpine",
                ports=[PortMapping(container=3000, host=3000)], depends_on=["db", "ghost"],
            ),
            ServiceModel(
                name="api", type="app", image="golang:1.23",
                entrypoint="./server", ports=[PortMapping(container=9000, host=9000)],
            ),
            ServiceModel(
                name="db", type="database", image="postgres:16-alpine",
                ports=[PortMapping(container=5432, host=5432)],
            ),
        ],
    )


@pytest.mark.parametrize(
    ("image", "runtime"),
    [
        ("python:3.12-slim", "python"),
        ("docker.io/library/node:20", "node"),
        ("golang:1.23-alpine", "go"),
        ("maven:3.9-eclipse-temurin-21", "java"),
        ("nginx:1.27", "generic"),
        ("mongo:7", "generic"),  # contains "go" but is not Go
    ],
)
def test_runtime_detection(image, runtime):
    assert _runtime(image) == runtime


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


class TestKubernetes:
    def test_built_services_deploy_the_ci_image(self, tmp_path: Path):
        Generator(tmp_path).generate(_two_app_model(), target="k8s")
        web = _load(tmp_path / "k8s" / "web-deployment.yaml")
        db = _load(tmp_path / "k8s" / "db-deployment.yaml")

        assert web["spec"]["template"]["spec"]["containers"][0]["image"] == "ghcr.io/shop/web:latest"
        assert db["spec"]["template"]["spec"]["containers"][0]["image"] == "postgres:16-alpine"

    def test_built_services_do_not_override_image_cmd(self, tmp_path: Path):
        # A shell-wrapped command would break distroless (Go) images.
        Generator(tmp_path).generate(_two_app_model(), target="k8s")
        api = _load(tmp_path / "k8s" / "api-deployment.yaml")
        assert "command" not in api["spec"]["template"]["spec"]["containers"][0]

    def test_init_containers_wait_on_real_ports(self, tmp_path: Path):
        Generator(tmp_path).generate(_two_app_model(), target="k8s")
        web = _load(tmp_path / "k8s" / "web-deployment.yaml")
        inits = web["spec"]["template"]["spec"]["initContainers"]

        # "ghost" isn't a known service, so only "db" is waited on.
        assert [c["name"] for c in inits] == ["wait-for-db"]
        assert "nc -z db 5432" in inits[0]["command"][2]

    def test_each_app_gets_its_own_ingress_host(self, tmp_path: Path):
        Generator(tmp_path).generate(_two_app_model(), target="k8s")
        ingress = _load(tmp_path / "k8s" / "ingress.yaml")

        hosts = [r["host"] for r in ingress["spec"]["rules"]]
        assert hosts == ["shop.example.com", "api.shop.example.com"]
        assert ingress["spec"]["ingressClassName"] == "nginx"
        assert "nginx.ingress.kubernetes.io/rewrite-target" not in ingress["metadata"]["annotations"]

    def test_volumes_get_claims(self, tmp_path: Path, sample_model):
        Generator(tmp_path).generate(sample_model, target="k8s")
        pvc = _load(tmp_path / "k8s" / "pgdata-pvc.yaml")
        assert pvc["kind"] == "PersistentVolumeClaim"
        assert pvc["metadata"]["name"] == "pgdata"


class TestDockerfiles:
    def test_go_uses_distroless_entrypoint(self, tmp_path: Path):
        Generator(tmp_path).generate(_two_app_model(), target="compose")
        dockerfile = (tmp_path / "Dockerfile.api").read_text()
        assert 'ENTRYPOINT ["/server"]' in dockerfile
        assert "CMD ./server" not in dockerfile

    def test_privileged_port_keeps_root(self, tmp_path: Path):
        model = InfraModel(
            project_name="p",
            routing=RoutingModel(domain="p.example.com"),
            services=[ServiceModel(
                name="web", type="app", image="python:3.12-slim",
                ports=[PortMapping(container=80, host=80)],
            )],
        )
        Generator(tmp_path).generate(model, target="compose")
        assert "USER" not in (tmp_path / "Dockerfile.web").read_text()

    def test_existing_dockerignore_is_left_alone(self, tmp_repo_with_state: Path, sample_model):
        ignore = tmp_repo_with_state / ".dockerignore"
        ignore.write_text("mine\n")

        files = Generator(tmp_repo_with_state).generate(sample_model, target="compose", force=True)

        assert ignore not in files
        assert ignore.read_text() == "mine\n"

    def test_dockerignore_created_when_missing(self, tmp_path: Path, sample_model):
        Generator(tmp_path).generate(sample_model, target="compose")
        assert ".git" in (tmp_path / ".dockerignore").read_text().splitlines()


class TestCompose:
    def test_compose_is_valid_without_swarm_only_keys(self, tmp_path: Path, sample_model):
        Generator(tmp_path).generate(sample_model, target="compose")
        compose = _load(tmp_path / "docker-compose.yml")

        assert "version" not in compose
        assert "secrets" not in compose  # external secrets need swarm
        assert compose["services"]["web"]["environment"]["SECRET_TOKEN"] == "${SECRET_TOKEN}"

    def test_env_example_lists_required_vars(self, tmp_path: Path, sample_model):
        Generator(tmp_path).generate(sample_model, target="compose")
        lines = (tmp_path / ".env.example").read_text().splitlines()
        assert {"API_KEY=", "SECRET_TOKEN=", "POSTGRES_PASSWORD="} <= set(lines)
