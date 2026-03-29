"""Pydantic v2 Infra Model -- the central contract between the AI Planner and all generators.

Serialized to disk as ``.ai-infra/infra_model.v1.json``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Version constant
# ---------------------------------------------------------------------------

SCHEMA_VERSION: str = "1.0"
INFRA_MODEL_FILENAME: str = "infra_model.v1.json"
INFRA_MODEL_DIR: str = ".ai-infra"


# ---------------------------------------------------------------------------
# Environment variable models (discriminated union on ``kind``)
# ---------------------------------------------------------------------------


class LiteralEnv(BaseModel):
    """An environment variable whose value is provided inline."""

    kind: Literal["literal"] = "literal"
    value: str

    model_config = ConfigDict(frozen=True)


class RefEnv(BaseModel):
    """An environment variable that references a host / CI environment variable."""

    kind: Literal["ref"] = "ref"
    ref: str

    model_config = ConfigDict(frozen=True)


class SecretEnv(BaseModel):
    """An environment variable sourced from a secrets manager or sealed-secret."""

    kind: Literal["secret"] = "secret"
    ref: str

    model_config = ConfigDict(frozen=True)


EnvVar = Annotated[
    Union[LiteralEnv, RefEnv, SecretEnv],
    Field(discriminator="kind"),
]


# ---------------------------------------------------------------------------
# Port model
# ---------------------------------------------------------------------------


class PortMapping(BaseModel):
    """A single port mapping for a service container."""

    container: int = Field(..., gt=0, le=65535, description="Port inside the container.")
    host: int = Field(..., gt=0, le=65535, description="Port exposed on the host / node.")
    protocol: Literal["TCP", "UDP"] = Field(
        default="TCP",
        description="Transport protocol.",
    )

    model_config = ConfigDict(frozen=True)


# ---------------------------------------------------------------------------
# Volume model
# ---------------------------------------------------------------------------


class VolumeMount(BaseModel):
    """A named volume mount for a service."""

    name: str = Field(..., min_length=1, description="Volume name.")
    mount_path: str = Field(..., min_length=1, description="Mount path inside the container.")

    model_config = ConfigDict(frozen=True)


# ---------------------------------------------------------------------------
# Sizing model
# ---------------------------------------------------------------------------


class SizingModel(BaseModel):
    """Resource sizing and scaling hints for a service."""

    scale: Literal["dev", "prod", "heavy"] = Field(
        default="dev",
        description="Deployment scale profile.",
    )
    replicas: int = Field(default=1, ge=1, description="Number of replicas.")
    cpu_requests: str = Field(default="100m", description="Kubernetes CPU request (e.g. '100m').")
    cpu_limits: str = Field(default="500m", description="Kubernetes CPU limit (e.g. '500m').")
    memory_requests: str = Field(
        default="256Mi",
        description="Kubernetes memory request (e.g. '256Mi').",
    )
    memory_limits: str = Field(
        default="512Mi",
        description="Kubernetes memory limit (e.g. '512Mi').",
    )
    workload_type: Literal["latency-sensitive", "batch", "background", "api"] = Field(
        default="api",
        description="Workload classification hint for the scheduler.",
    )

    model_config = ConfigDict(frozen=True)


# ---------------------------------------------------------------------------
# Service model
# ---------------------------------------------------------------------------


class ServiceModel(BaseModel):
    """A single deployable service (app, database, cache, worker)."""

    name: str = Field(..., min_length=1, description="Unique service name within the project.")
    type: Literal["app", "database", "cache", "worker"] = Field(
        ...,
        description="Service archetype.",
    )
    image: str = Field(..., min_length=1, description="Container image reference.")
    entrypoint: str | None = Field(
        default=None,
        description="Optional entrypoint / command override for the container.",
    )
    ports: list[PortMapping] = Field(default_factory=list, description="Exposed port mappings.")
    depends_on: list[str] = Field(
        default_factory=list,
        description="Names of services this service depends on.",
    )
    env: dict[str, EnvVar] = Field(
        default_factory=dict,
        description="Environment variables keyed by name.",
    )
    sizing: SizingModel = Field(
        default_factory=SizingModel,
        description="Resource sizing and scaling configuration.",
    )
    volumes: list[VolumeMount] = Field(
        default_factory=list,
        description="Volume mounts for the service.",
    )

    model_config = ConfigDict(frozen=True)


# ---------------------------------------------------------------------------
# Routing model
# ---------------------------------------------------------------------------


class RoutingModel(BaseModel):
    """Domain and ingress routing configuration."""

    domain: str = Field(..., min_length=1, description="Primary domain for the project.")
    ingress_controller: Literal["nginx", "traefik", "alb"] = Field(
        default="nginx",
        description="Ingress controller type.",
    )

    model_config = ConfigDict(frozen=True)


# ---------------------------------------------------------------------------
# Capabilities model
# ---------------------------------------------------------------------------


class CapabilitiesModel(BaseModel):
    """High-level capability flags that influence generator decisions."""

    needs_gpu: bool = Field(default=False, description="Whether any service requires GPU access.")
    latency_sensitive: bool = Field(
        default=False,
        description="Whether the workload is latency-sensitive.",
    )
    multi_tenant: bool = Field(
        default=False,
        description="Whether the deployment is multi-tenant.",
    )
    slo_hints: str | None = Field(
        default=None,
        description="Optional SLO hints (e.g. 'p99 < 200ms').",
    )

    model_config = ConfigDict(frozen=True)


# ---------------------------------------------------------------------------
# Cluster assumptions model
# ---------------------------------------------------------------------------


class ClusterAssumptionsModel(BaseModel):
    """Assumptions about the target Kubernetes cluster environment."""

    ingress_controller: Literal["nginx", "traefik", "alb"] = Field(
        default="nginx",
        description="Expected ingress controller on the cluster.",
    )
    ingress_class_name: str = Field(
        default="nginx",
        description="Kubernetes IngressClass name.",
    )
    tls_enabled: bool = Field(default=True, description="Whether TLS is enabled on ingress.")
    cert_manager: bool = Field(
        default=True,
        description="Whether cert-manager is available for automatic TLS certificates.",
    )
    storage_class: str = Field(
        default="standard",
        description="Default Kubernetes StorageClass name.",
    )

    model_config = ConfigDict(frozen=True)


# ---------------------------------------------------------------------------
# Helm chart model
# ---------------------------------------------------------------------------


class HelmModel(BaseModel):
    """Configuration for Helm chart generation."""

    enabled: bool = Field(default=False, description="Whether to generate a Helm chart.")
    chart_name: str | None = Field(
        default=None,
        description="Helm chart name. Defaults to project_name if not set.",
    )
    chart_version: str = Field(default="0.1.0", description="Helm chart version.")
    app_version: str = Field(default="1.0.0", description="Application version for the chart.")
    values_overrides: dict[str, Any] = Field(
        default_factory=dict,
        description="Extra values to inject into values.yaml.",
    )

    model_config = ConfigDict(frozen=True)


# ---------------------------------------------------------------------------
# IaC / cluster provisioning model
# ---------------------------------------------------------------------------


class IaCModel(BaseModel):
    """Configuration for Infrastructure-as-Code cluster provisioning."""

    enabled: bool = Field(default=False, description="Whether to generate IaC files.")
    tool: Literal["terraform", "pulumi", "cdk"] = Field(
        default="terraform",
        description="IaC tool to generate for.",
    )
    cloud_provider: Literal["aws", "gcp", "azure"] = Field(
        default="aws",
        description="Target cloud provider.",
    )
    region: str = Field(default="us-east-1", description="Cloud region for provisioning.")
    cluster_name: str | None = Field(
        default=None,
        description="Kubernetes cluster name. Defaults to project_name if not set.",
    )
    node_count: int = Field(default=3, ge=1, description="Number of worker nodes.")
    node_instance_type: str = Field(
        default="t3.medium",
        description="Instance type for worker nodes.",
    )
    kubernetes_version: str = Field(
        default="1.29",
        description="Kubernetes version for the managed cluster.",
    )

    model_config = ConfigDict(frozen=True)


# ---------------------------------------------------------------------------
# Multi-CI/CD model
# ---------------------------------------------------------------------------


class CICDModel(BaseModel):
    """Configuration for CI/CD pipeline generation across multiple providers."""

    providers: list[
        Literal["github_actions", "gitlab_ci", "bitbucket_pipelines", "circleci"]
    ] = Field(
        default_factory=lambda: ["github_actions"],
        description="CI/CD providers to generate pipelines for.",
    )
    registry: str = Field(default="ghcr.io", description="Container registry.")
    cluster_auth: Literal["aws", "gke", "azure", "kubeconfig"] = Field(
        default="kubeconfig",
        description="Cluster authentication method for deployment steps.",
    )
    run_tests: bool = Field(default=True, description="Whether to include a test step.")
    lint: bool = Field(default=True, description="Whether to include a lint step.")
    auto_deploy: bool = Field(
        default=True,
        description="Whether to auto-deploy on push to main.",
    )

    model_config = ConfigDict(frozen=True)


# ---------------------------------------------------------------------------
# Monitoring / observability model
# ---------------------------------------------------------------------------


class MonitoringModel(BaseModel):
    """Configuration for monitoring and observability stack generation."""

    enabled: bool = Field(default=False, description="Whether to generate monitoring configs.")
    prometheus: bool = Field(
        default=True,
        description="Generate Prometheus ServiceMonitor and scrape configs.",
    )
    grafana: bool = Field(
        default=True,
        description="Generate Grafana dashboard JSON.",
    )
    alerting: bool = Field(
        default=True,
        description="Generate Prometheus alerting rules.",
    )
    metrics_port: int = Field(
        default=9090,
        gt=0,
        le=65535,
        description="Port for the metrics endpoint (e.g. /metrics).",
    )
    metrics_path: str = Field(
        default="/metrics",
        description="HTTP path for the Prometheus scrape endpoint.",
    )
    alert_thresholds: dict[str, float] = Field(
        default_factory=lambda: {
            "cpu_percent": 80.0,
            "memory_percent": 85.0,
            "error_rate_5xx": 5.0,
            "p99_latency_ms": 500.0,
        },
        description="Alert threshold values.",
    )

    model_config = ConfigDict(frozen=True)


# ---------------------------------------------------------------------------
# Multi-tenancy model
# ---------------------------------------------------------------------------


class TenantModel(BaseModel):
    """A single tenant in a multi-tenant deployment."""

    name: str = Field(..., min_length=1, description="Tenant identifier.")
    namespace: str | None = Field(
        default=None,
        description="Kubernetes namespace. Defaults to tenant name.",
    )
    resource_quota_cpu: str = Field(default="4", description="CPU quota for the tenant.")
    resource_quota_memory: str = Field(default="8Gi", description="Memory quota for the tenant.")
    custom_domain: str | None = Field(
        default=None,
        description="Custom domain for this tenant's ingress.",
    )

    model_config = ConfigDict(frozen=True)


class MultiTenancyModel(BaseModel):
    """Configuration for multi-tenant control plane and namespace isolation."""

    enabled: bool = Field(default=False, description="Whether multi-tenancy is enabled.")
    isolation_level: Literal["namespace", "cluster"] = Field(
        default="namespace",
        description="Isolation strategy for tenants.",
    )
    tenants: list[TenantModel] = Field(
        default_factory=list,
        description="List of tenant configurations.",
    )
    network_policies: bool = Field(
        default=True,
        description="Generate NetworkPolicy resources for tenant isolation.",
    )
    shared_services: list[str] = Field(
        default_factory=list,
        description="Service names shared across all tenants (e.g. a shared database).",
    )

    model_config = ConfigDict(frozen=True)


# ---------------------------------------------------------------------------
# Root Infra Model
# ---------------------------------------------------------------------------


class InfraModel(BaseModel):
    """Root infrastructure model -- the single source of truth consumed by all generators.

    Serialize with :pymeth:`save` and deserialize with :pymeth:`load`.
    """

    version: str = Field(
        default=SCHEMA_VERSION,
        description="Schema version for forward-compatible evolution.",
    )
    project_name: str = Field(..., min_length=1, description="Human-readable project identifier.")
    routing: RoutingModel = Field(..., description="Domain and ingress configuration.")
    capabilities: CapabilitiesModel = Field(
        default_factory=CapabilitiesModel,
        description="High-level capability flags.",
    )
    services: list[ServiceModel] = Field(
        ...,
        min_length=1,
        description="One or more services that compose the project.",
    )
    cluster_assumptions: ClusterAssumptionsModel = Field(
        default_factory=ClusterAssumptionsModel,
        description="Assumptions about the target cluster environment.",
    )
    helm: HelmModel = Field(
        default_factory=HelmModel,
        description="Helm chart generation configuration.",
    )
    iac: IaCModel = Field(
        default_factory=IaCModel,
        description="Infrastructure-as-Code cluster provisioning configuration.",
    )
    cicd: CICDModel = Field(
        default_factory=CICDModel,
        description="CI/CD pipeline generation configuration.",
    )
    monitoring: MonitoringModel = Field(
        default_factory=MonitoringModel,
        description="Monitoring and observability configuration.",
    )
    multi_tenancy: MultiTenancyModel = Field(
        default_factory=MultiTenancyModel,
        description="Multi-tenant control plane configuration.",
    )

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "version": "1.0",
                    "project_name": "my-saas-app",
                    "routing": {
                        "domain": "app.example.com",
                        "ingress_controller": "nginx",
                    },
                    "capabilities": {
                        "needs_gpu": False,
                        "latency_sensitive": True,
                        "multi_tenant": False,
                        "slo_hints": "p99 < 200ms",
                    },
                    "services": [
                        {
                            "name": "web",
                            "type": "app",
                            "image": "python:3.11-slim",
                            "entrypoint": "uvicorn main:app --host 0.0.0.0 --port 8000",
                            "ports": [
                                {"container": 8000, "host": 8000, "protocol": "TCP"},
                            ],
                            "depends_on": ["postgres", "redis"],
                            "env": {
                                "DATABASE_URL": {
                                    "kind": "literal",
                                    "value": "postgres://user:pass@postgres:5432/db",
                                },
                                "OPENAI_API_KEY": {
                                    "kind": "ref",
                                    "ref": "OPENAI_API_KEY",
                                },
                                "STRIPE_SECRET_KEY": {
                                    "kind": "secret",
                                    "ref": "STRIPE_SECRET_KEY",
                                },
                            },
                            "sizing": {
                                "scale": "prod",
                                "replicas": 2,
                                "cpu_requests": "250m",
                                "cpu_limits": "1",
                                "memory_requests": "512Mi",
                                "memory_limits": "1Gi",
                                "workload_type": "latency-sensitive",
                            },
                            "volumes": [],
                        },
                        {
                            "name": "postgres",
                            "type": "database",
                            "image": "postgres:16-alpine",
                            "ports": [
                                {"container": 5432, "host": 5432, "protocol": "TCP"},
                            ],
                            "depends_on": [],
                            "env": {
                                "POSTGRES_PASSWORD": {
                                    "kind": "secret",
                                    "ref": "POSTGRES_PASSWORD",
                                },
                            },
                            "sizing": {
                                "scale": "prod",
                                "replicas": 1,
                                "cpu_requests": "250m",
                                "cpu_limits": "1",
                                "memory_requests": "512Mi",
                                "memory_limits": "2Gi",
                                "workload_type": "latency-sensitive",
                            },
                            "volumes": [
                                {"name": "pgdata", "mount_path": "/var/lib/postgresql/data"},
                            ],
                        },
                        {
                            "name": "redis",
                            "type": "cache",
                            "image": "redis:7-alpine",
                            "ports": [
                                {"container": 6379, "host": 6379, "protocol": "TCP"},
                            ],
                            "depends_on": [],
                            "env": {},
                            "sizing": {
                                "scale": "prod",
                                "replicas": 1,
                                "cpu_requests": "100m",
                                "cpu_limits": "500m",
                                "memory_requests": "128Mi",
                                "memory_limits": "256Mi",
                                "workload_type": "latency-sensitive",
                            },
                            "volumes": [],
                        },
                    ],
                    "cluster_assumptions": {
                        "ingress_controller": "nginx",
                        "ingress_class_name": "nginx",
                        "tls_enabled": True,
                        "cert_manager": True,
                        "storage_class": "standard",
                    },
                }
            ]
        },
    )

    # -- Serialization helpers -----------------------------------------------

    def save(self, project_root: str | Path) -> Path:
        """Persist the model to ``<project_root>/.ai-infra/infra_model.v1.json``.

        Creates the directory if it does not exist.  Returns the written path.
        """
        out_dir = Path(project_root) / INFRA_MODEL_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / INFRA_MODEL_FILENAME
        out_path.write_text(
            self.model_dump_json(indent=2, by_alias=True) + "\n",
            encoding="utf-8",
        )
        return out_path

    @classmethod
    def load(cls, project_root: str | Path) -> "InfraModel":
        """Load and validate an ``InfraModel`` from disk.

        Raises ``FileNotFoundError`` if the file is missing and
        ``pydantic.ValidationError`` if the content is invalid.
        """
        in_path = Path(project_root) / INFRA_MODEL_DIR / INFRA_MODEL_FILENAME
        raw: dict[str, Any] = json.loads(in_path.read_text(encoding="utf-8"))
        return cls.model_validate(raw)
