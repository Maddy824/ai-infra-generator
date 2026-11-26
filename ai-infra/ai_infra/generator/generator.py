"""Generator -- renders Jinja2 templates into infrastructure files.

Supports targets: compose, k8s, ci, helm, iac, monitoring, tenancy, all.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, TemplateNotFound

from ai_infra.models.infra_model import InfraModel, ServiceModel
from ai_infra.state.state_manager import StateManager

logger = logging.getLogger(__name__)

# Path to the templates directory (sibling of this file)
_TEMPLATES_DIR = Path(__file__).parent / "templates"

# Every value accepted by ``Generator.generate(target=...)``.
TARGETS: tuple[str, ...] = (
    "compose", "k8s", "ci", "helm", "iac", "monitoring", "tenancy", "all",
)


# ---------------------------------------------------------------------------
# _ModelProxy -- attribute-style access for Jinja2 templates
# ---------------------------------------------------------------------------


class _ModelProxy:
    """Wrap a dict so Jinja2 templates can use dot-notation access.

    Also supports integer indexing for list items and iteration.
    """

    def __init__(self, data: Any) -> None:
        self._data = data

    def __getattr__(self, name: str) -> Any:
        if isinstance(self._data, dict):
            try:
                value = self._data[name]
            except KeyError:
                raise AttributeError(name) from None
            return _wrap(value)
        raise AttributeError(name)

    def __getitem__(self, key: Any) -> Any:
        value = self._data[key]
        return _wrap(value)

    def __iter__(self):
        for item in self._data:
            yield _wrap(item)

    def __len__(self) -> int:
        return len(self._data)

    def __bool__(self) -> bool:
        return bool(self._data)

    def __str__(self) -> str:
        return str(self._data)

    def __repr__(self) -> str:
        return f"_ModelProxy({self._data!r})"

    def items(self):
        if isinstance(self._data, dict):
            for k, v in self._data.items():
                yield k, _wrap(v)

    def get(self, key: str, default: Any = None) -> Any:
        if isinstance(self._data, dict):
            value = self._data.get(key, default)
            return _wrap(value) if value is not default else default
        return default


def _wrap(value: Any) -> Any:
    """Recursively wrap dicts and lists for template access."""
    if isinstance(value, dict):
        return _ModelProxy(value)
    if isinstance(value, list):
        return _ModelProxy(value)
    return value


# ---------------------------------------------------------------------------
# Template data -- the model dump plus values derived from it
# ---------------------------------------------------------------------------

_RUNTIME_PREFIXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("python", ("python", "pypy")),
    ("node", ("node",)),
    ("go", ("golang",)),
    ("java", ("maven", "gradle", "openjdk", "eclipse-temurin", "amazoncorretto")),
)


def _runtime(image: str) -> str:
    """Infer the language runtime from a base image like ``python:3.12-slim``."""
    name = image.rsplit("/", 1)[-1].split(":", 1)[0].split("@", 1)[0].lower()
    for runtime, prefixes in _RUNTIME_PREFIXES:
        if name.startswith(prefixes):
            return runtime
    return "generic"


def _is_built(svc: ServiceModel) -> bool:
    """App and worker services are built from the repo; others use stock images."""
    return svc.type in ("app", "worker")


def _service_data(model: InfraModel, svc: ServiceModel) -> dict[str, Any]:
    """Dump *svc* for templates, adding derived fields.

    - ``built``: whether the image is built from this repo (``Dockerfile.<name>``)
    - ``deploy_image``: what Kubernetes/Helm should run -- the image CI pushes
      for built services, the stock image otherwise
    - ``runtime``: python | node | go | java | generic
    - ``probe_port``: first TCP port, used for health probes
    - ``run_as_root``: the service binds a privileged port, so the image
      must not drop to a non-root user
    - ``wait_for``: ``[{name, port}]`` for dependencies that expose a port
    """
    by_name = {s.name: s for s in model.services}
    built = _is_built(svc)
    tcp_ports = [p.container for p in svc.ports if p.protocol == "TCP"]
    wait_for = [
        {"name": dep, "port": by_name[dep].ports[0].container}
        for dep in svc.depends_on
        if dep in by_name and by_name[dep].ports
    ]
    data = svc.model_dump()
    data.update(
        built=built,
        deploy_image=(
            f"{model.cicd.registry}/{model.project_name}/{svc.name}:latest" if built else svc.image
        ),
        runtime=_runtime(svc.image),
        probe_port=tcp_ports[0] if tcp_ports else None,
        # Binding ports < 1024 needs root inside the container.
        run_as_root=any(p.container < 1024 for p in svc.ports),
        wait_for=wait_for,
    )
    return data


def _env_refs(model: InfraModel, kinds: tuple[str, ...]) -> dict[str, str]:
    """Map env var name -> ref for every env var of the given *kinds*."""
    refs: dict[str, str] = {}
    for svc in model.services:
        for env_name, env_var in svc.env.items():
            if env_var.kind in kinds:
                refs[env_name] = env_var.ref
    return refs


def _model_data(model: InfraModel) -> dict[str, Any]:
    """Dump *model* for templates, with enriched service entries."""
    data = model.model_dump()
    data["services"] = [_service_data(model, s) for s in model.services]
    return data


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


class Generator:
    """Render Jinja2 templates into infrastructure files."""

    def __init__(self, repo_path: Path) -> None:
        self.repo_path = Path(repo_path).resolve()
        self.env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._state = StateManager(self.repo_path)
        self.skipped: list[Path] = []
        self.written: list[Path] = []
        self.blocked: list[Path] = []
        self._outputs: dict[Path, str] = {}

    def _protected(self, path: Path, force: bool) -> bool:
        """Check ownership and path safety before any output is written."""
        try:
            if path.resolve() != path or not path.is_relative_to(self.repo_path):
                return True
        except (OSError, RuntimeError):
            return True
        if any(parent.exists() and not parent.is_dir() for parent in path.parents):
            return True
        if not path.exists():
            return False
        if not path.is_file():
            return True
        rel = path.relative_to(self.repo_path).as_posix()
        if force and rel != ".dockerignore":
            return False
        # An existing dockerignore is never overwritten, even with force.
        return not self._state.is_tracked(rel) or self._state.was_modified(rel) or rel == ".dockerignore"

    def _render(self, model: InfraModel, target: str) -> dict[Path, str]:
        """Render all requested outputs before modifying the filesystem."""
        if target not in TARGETS:
            raise ValueError(
                f"Invalid target '{target}'. Choose from: {', '.join(TARGETS)}"
            )
        self._outputs = {}
        if target in ("compose", "all"):
            self._generate_dockerfiles(model)
            self._generate_compose(model)
        if target in ("k8s", "all"):
            self._generate_k8s(model)
        if target in ("ci", "all"):
            self._generate_ci(model)
        if target in ("helm", "all") and model.helm.enabled:
            self._generate_helm(model)
        if target in ("iac", "all") and model.iac.enabled:
            self._generate_iac(model)
        if target in ("monitoring", "all") and model.monitoring.enabled:
            self._generate_monitoring(model)
        if target in ("tenancy", "all") and model.multi_tenancy.enabled:
            self._generate_tenancy(model)
        return self._outputs

    def generate(
        self,
        model: InfraModel,
        target: str = "compose",
        force: bool = False,
        *,
        require_all: bool = False,
    ) -> list[Path]:
        """Render and write outputs, respecting existing file ownership.

        With require_all, preflight every output and stop before writes if
        any manifest is protected. An existing .dockerignore is always kept.
        """
        self.skipped = []
        self.written = []
        self.blocked = []
        outputs = self._render(model, target)
        pending = {}
        for path, content in outputs.items():
            protected = self._protected(path, force)
            is_dockerignore = path == self.repo_path / ".dockerignore"
            # An unchanged, tracked dockerignore needs no regeneration.
            if (is_dockerignore and not path.is_symlink() and path.is_file()
                    and self._state.is_tracked(".dockerignore")
                    and path.read_bytes() == content.encode("utf-8")):
                continue
            if protected:
                self.skipped.append(path)
                logger.warning("Skipping protected output %s.", path)
                if not is_dockerignore:
                    self.blocked.append(path)
                continue
            rel = path.relative_to(self.repo_path).as_posix()
            if (path.is_file() and path.read_bytes() == content.encode("utf-8")
                    and self._state.is_tracked(rel) and not self._state.was_modified(rel)):
                continue
            pending[path] = content
        if require_all and self.blocked:
            return []

        self._state.init_state_dir()
        for path, content in pending.items():
            # Recheck in case a file changed after preflight.
            if self._protected(path, force):
                self.skipped.append(path)
                if path != self.repo_path / ".dockerignore":
                    self.blocked.append(path)
                    if require_all:
                        break
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            self.written.append(path)
            self._state.mark_clean(path.relative_to(self.repo_path).as_posix())
        return self.written

    # -- Dockerfiles -------------------------------------------------------

    def _generate_dockerfiles(self, model: InfraModel) -> None:
        for svc in model.services:
            if svc.type in ("database", "cache"):
                continue
            ctx = self._service_context(model, svc)
            tmpl = self.env.get_template("docker/Dockerfile.j2")
            path = self.repo_path / f"Dockerfile.{svc.name}"
            self._outputs[path] = tmpl.render(**ctx)

        # Keep VCS data, local envs, secrets and build output out of the
        # build context. Always preserve an existing project ignore file.
        if any(_is_built(s) for s in model.services):
            tmpl = self.env.get_template("docker/dockerignore.j2")
            path = self.repo_path / ".dockerignore"
            self._outputs[path] = tmpl.render()

    # -- Docker Compose ----------------------------------------------------

    def _generate_compose(self, model: InfraModel) -> None:
        model_data = _wrap(_model_data(model))
        tmpl = self.env.get_template("compose/docker-compose.yml.j2")
        path = self.repo_path / "docker-compose.yml"
        self._outputs[path] = tmpl.render(model=model_data)

        # Compose interpolates ref/secret env vars from .env -- document
        # which ones are needed.
        env_refs = _env_refs(model, ("ref", "secret"))
        if env_refs:
            tmpl = self.env.get_template("compose/env.example.j2")
            path = self.repo_path / ".env.example"
            self._outputs[path] = tmpl.render(env_refs=env_refs)

    # -- Kubernetes --------------------------------------------------------

    def _generate_k8s(self, model: InfraModel) -> None:
        k8s_dir = self.repo_path / "k8s"

        model_data = _wrap(_model_data(model))

        for svc in model.services:
            ctx = self._service_context(model, svc)

            # Deployment
            tmpl = self.env.get_template("k8s/deployment.yaml.j2")
            path = k8s_dir / f"{svc.name}-deployment.yaml"
            self._outputs[path] = tmpl.render(**ctx)

            # Service (if ports)
            if svc.ports:
                tmpl = self.env.get_template("k8s/service.yaml.j2")
                path = k8s_dir / f"{svc.name}-service.yaml"
                self._outputs[path] = tmpl.render(**ctx)

            # HPA (if prod or heavy scale)
            if svc.sizing.scale in ("prod", "heavy") and svc.type == "app":
                tmpl = self.env.get_template("k8s/hpa.yaml.j2")
                path = k8s_dir / f"{svc.name}-hpa.yaml"
                self._outputs[path] = tmpl.render(**ctx)

        # Ingress (for app services).  The first app is served at the root
        # domain; any others get a subdomain each, so no app has its paths
        # rewritten or shadowed.
        app_services = [s for s in model.services if s.type == "app" and s.ports]
        if app_services:
            domain = model.routing.domain
            routes = []
            for i, svc in enumerate(app_services):
                data = _service_data(model, svc)
                data["host"] = domain if i == 0 else f"{svc.name}.{domain}"
                routes.append(_wrap(data))
            tmpl = self.env.get_template("k8s/ingress.yaml.j2")
            path = k8s_dir / "ingress.yaml"
            self._outputs[path] = tmpl.render(model=model_data, app_services=routes)

        # PersistentVolumeClaims referenced by the deployments' volumes
        claims: dict[str, str] = {}
        for svc in model.services:
            for vol in svc.volumes:
                claims.setdefault(vol.name, "10Gi" if svc.sizing.scale != "dev" else "1Gi")
        for claim, size in claims.items():
            tmpl = self.env.get_template("k8s/pvc.yaml.j2")
            path = k8s_dir / f"{claim}-pvc.yaml"
            self._outputs[path] = tmpl.render(model=model_data, claim=claim, size=size)

        # ConfigMap (for ref envs)
        ref_envs = _env_refs(model, ("ref",))
        if ref_envs:
            tmpl = self.env.get_template("k8s/configmap.yaml.j2")
            path = k8s_dir / "configmap.yaml"
            self._outputs[path] = tmpl.render(model=model_data, ref_envs=ref_envs)

        # Secret placeholder (for secret envs)
        secret_envs = _env_refs(model, ("secret",))
        if secret_envs:
            tmpl = self.env.get_template("k8s/secret.yaml.j2")
            path = k8s_dir / "secret.yaml"
            self._outputs[path] = tmpl.render(model=model_data, secret_envs=secret_envs)

    # -- CI/CD -------------------------------------------------------------

    def _generate_ci(self, model: InfraModel) -> None:
        cicd = model.cicd
        model_data = _wrap(_model_data(model))

        _CI_FILE_MAP = {
            "github_actions": ("ci/github-actions.yml.j2", ".github/workflows/deploy.yml"),
            "gitlab_ci": ("ci/gitlab-ci.yml.j2", ".gitlab-ci.yml"),
            "bitbucket_pipelines": ("ci/bitbucket-pipelines.yml.j2", "bitbucket-pipelines.yml"),
            "circleci": ("ci/circleci.yml.j2", ".circleci/config.yml"),
        }

        app_services = [s for s in model.services if s.type in ("app", "worker")]
        ctx = {
            "model": model_data,
            "cicd": _wrap(cicd.model_dump()),
            "app_services": [_wrap(_service_data(model, s)) for s in app_services],
        }

        for provider in cicd.providers:
            if provider not in _CI_FILE_MAP:
                logger.warning("Unknown CI provider: %s", provider)
                continue
            template_name, output_path = _CI_FILE_MAP[provider]
            tmpl = self.env.get_template(template_name)
            content = tmpl.render(**ctx)
            path = self.repo_path / output_path
            self._outputs[path] = content

    # -- Helm charts -------------------------------------------------------

    def _generate_helm(self, model: InfraModel) -> None:
        helm = model.helm
        chart_name = helm.chart_name or model.project_name
        chart_dir = self.repo_path / "helm" / chart_name
        templates_dir = chart_dir / "templates"

        model_data = _wrap(_model_data(model))

        # Chart.yaml
        tmpl = self.env.get_template("helm/Chart.yaml.j2")
        path = chart_dir / "Chart.yaml"
        self._outputs[path] = tmpl.render(
            chart_name=chart_name,
            chart_version=helm.chart_version,
            app_version=helm.app_version,
            model=model_data,
        )

        # values.yaml
        tmpl = self.env.get_template("helm/values.yaml.j2")
        path = chart_dir / "values.yaml"
        self._outputs[path] = tmpl.render(model=model_data, helm=_wrap(helm.model_dump()))

        # templates/deployment.yaml
        tmpl = self.env.get_template("helm/templates/deployment.yaml.j2")
        path = templates_dir / "deployment.yaml"
        self._outputs[path] = tmpl.render(model=model_data)

        # templates/service.yaml
        tmpl = self.env.get_template("helm/templates/service.yaml.j2")
        path = templates_dir / "service.yaml"
        self._outputs[path] = tmpl.render(model=model_data)

        # templates/ingress.yaml
        tmpl = self.env.get_template("helm/templates/ingress.yaml.j2")
        path = templates_dir / "ingress.yaml"
        self._outputs[path] = tmpl.render(model=model_data)

    # -- IaC / Terraform ---------------------------------------------------

    def _generate_iac(self, model: InfraModel) -> None:
        iac = model.iac
        model_data = _wrap(_model_data(model))

        if iac.tool != "terraform":
            logger.warning("IaC tool '%s' not yet supported; only 'terraform' is implemented.", iac.tool)
            return

        provider = iac.cloud_provider
        template_path = f"iac/terraform/{provider}/main.tf.j2"

        try:
            tmpl = self.env.get_template(template_path)
        except TemplateNotFound:
            logger.warning("No Terraform template for provider '%s'.", provider)
            return

        tf_dir = self.repo_path / "terraform"

        path = tf_dir / "main.tf"
        self._outputs[path] = tmpl.render(
            model=model_data,
            iac=_wrap(iac.model_dump()),
        )

    # -- Monitoring --------------------------------------------------------

    def _generate_monitoring(self, model: InfraModel) -> None:
        mon = model.monitoring
        model_data = _wrap(_model_data(model))
        mon_dir = self.repo_path / "monitoring"

        app_services = [s for s in model.services if s.type in ("app", "worker")]

        if mon.prometheus:
            for svc in app_services:
                tmpl = self.env.get_template("monitoring/servicemonitor.yaml.j2")
                ctx = {
                    "model": model_data,
                    "svc": _wrap(_service_data(model, svc)),
                    "monitoring": _wrap(mon.model_dump()),
                }
                path = mon_dir / f"{svc.name}-servicemonitor.yaml"
                self._outputs[path] = tmpl.render(**ctx)

        if mon.alerting:
            tmpl = self.env.get_template("monitoring/alerting-rules.yaml.j2")
            ctx = {
                "model": model_data,
                "app_services": [_wrap(_service_data(model, s)) for s in app_services],
                "monitoring": _wrap(mon.model_dump()),
                "thresholds": _wrap(mon.alert_thresholds),
            }
            path = mon_dir / "alerting-rules.yaml"
            self._outputs[path] = tmpl.render(**ctx)

        if mon.grafana:
            tmpl = self.env.get_template("monitoring/grafana-dashboard.json.j2")
            ctx = {
                "model": model_data,
                "app_services": [_wrap(_service_data(model, s)) for s in app_services],
                "monitoring": _wrap(mon.model_dump()),
                "thresholds": _wrap(mon.alert_thresholds),
            }
            path = mon_dir / "grafana-dashboard.json"
            self._outputs[path] = tmpl.render(**ctx)

    # -- Multi-tenancy -----------------------------------------------------

    def _generate_tenancy(self, model: InfraModel) -> None:
        mt = model.multi_tenancy
        model_data = _wrap(_model_data(model))

        for tenant in mt.tenants:
            ns = tenant.namespace or tenant.name
            tenant_data = _wrap(tenant.model_dump())
            tenant_dir = self.repo_path / "k8s" / "tenants" / ns

            ctx = {
                "model": model_data,
                "tenant": tenant_data,
                "namespace": ns,
                "multi_tenancy": _wrap(mt.model_dump()),
            }

            # Namespace
            tmpl = self.env.get_template("tenancy/namespace.yaml.j2")
            path = tenant_dir / "namespace.yaml"
            self._outputs[path] = tmpl.render(**ctx)

            # ResourceQuota
            tmpl = self.env.get_template("tenancy/resource-quota.yaml.j2")
            path = tenant_dir / "resource-quota.yaml"
            self._outputs[path] = tmpl.render(**ctx)

            # NetworkPolicy
            if mt.network_policies:
                tmpl = self.env.get_template("tenancy/network-policy.yaml.j2")
                path = tenant_dir / "network-policy.yaml"
                self._outputs[path] = tmpl.render(**ctx)

    # -- Helpers -----------------------------------------------------------

    @staticmethod
    def _service_context(model: InfraModel, svc: ServiceModel) -> dict:
        """Build a template context dict for a single service."""
        return {
            "model": _wrap(_model_data(model)),
            "svc": _wrap(_service_data(model, svc)),
        }
