"""Generator -- renders Jinja2 templates into infrastructure files.

Supports targets: compose, k8s, ci, helm, iac, monitoring, tenancy, all.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, TemplateNotFound

from ai_infra.models.infra_model import InfraModel
from ai_infra.state.state_manager import StateManager

logger = logging.getLogger(__name__)

# Path to the templates directory (sibling of this file)
_TEMPLATES_DIR = Path(__file__).parent / "templates"


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
                raise AttributeError(name)
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

    def _write_if_changed(
        self, path: Path, content: str, force: bool = False,
    ) -> bool:
        """Write *content* to *path* only if it differs from what's on disk.

        When *force* is ``False`` and the file already exists with identical
        content, the write is skipped and ``False`` is returned.  Otherwise
        the file is written, its state entry is marked clean, and ``True`` is
        returned.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        if not force and path.exists():
            existing = path.read_text(encoding="utf-8")
            if existing == content:
                return False
        path.write_text(content, encoding="utf-8")
        # Track the file in state.json for incremental regeneration.
        rel = str(path.relative_to(self.repo_path))
        try:
            if self._state.exists():
                self._state.mark_clean(rel)
        except Exception:  # noqa: BLE001
            pass  # non-critical; don't fail generation over state tracking
        return True

    def generate(
        self,
        model: InfraModel,
        target: str = "compose",
        force: bool = False,
    ) -> list[Path]:
        """Generate infrastructure files for the given target.

        When *force* is ``False``, files whose content has not changed since
        the last generation are skipped (incremental regeneration).

        Returns a list of paths to the files that were actually written.
        """
        self._force = force
        generated: list[Path] = []

        if target in ("compose", "all"):
            generated.extend(self._generate_dockerfiles(model))
            generated.extend(self._generate_compose(model))

        if target in ("k8s", "all"):
            generated.extend(self._generate_k8s(model))

        if target in ("ci", "all"):
            generated.extend(self._generate_ci(model))

        if target in ("helm", "all"):
            if model.helm.enabled:
                generated.extend(self._generate_helm(model))

        if target in ("iac", "all"):
            if model.iac.enabled:
                generated.extend(self._generate_iac(model))

        if target in ("monitoring", "all"):
            if model.monitoring.enabled:
                generated.extend(self._generate_monitoring(model))

        if target in ("tenancy", "all"):
            if model.multi_tenancy.enabled:
                generated.extend(self._generate_tenancy(model))

        return generated

    # -- Dockerfiles -------------------------------------------------------

    def _generate_dockerfiles(self, model: InfraModel) -> list[Path]:
        generated: list[Path] = []
        for svc in model.services:
            if svc.type in ("database", "cache"):
                continue
            ctx = self._service_context(model, svc)
            tmpl = self.env.get_template("docker/Dockerfile.j2")
            path = self.repo_path / f"Dockerfile.{svc.name}"
            if self._write_if_changed(path, tmpl.render(**ctx), self._force):
                generated.append(path)
        return generated

    # -- Docker Compose ----------------------------------------------------

    def _generate_compose(self, model: InfraModel) -> list[Path]:
        model_data = _wrap(model.model_dump())
        tmpl = self.env.get_template("compose/docker-compose.yml.j2")
        path = self.repo_path / "docker-compose.yml"
        if self._write_if_changed(path, tmpl.render(model=model_data), self._force):
            return [path]
        return []

    # -- Kubernetes --------------------------------------------------------

    def _generate_k8s(self, model: InfraModel) -> list[Path]:
        generated: list[Path] = []
        k8s_dir = self.repo_path / "k8s"
        k8s_dir.mkdir(parents=True, exist_ok=True)

        model_data = _wrap(model.model_dump())

        for svc in model.services:
            ctx = self._service_context(model, svc)

            # Deployment
            tmpl = self.env.get_template("k8s/deployment.yaml.j2")
            path = k8s_dir / f"{svc.name}-deployment.yaml"
            if self._write_if_changed(path, tmpl.render(**ctx), self._force):
                generated.append(path)

            # Service (if ports)
            if svc.ports:
                tmpl = self.env.get_template("k8s/service.yaml.j2")
                path = k8s_dir / f"{svc.name}-service.yaml"
                if self._write_if_changed(path, tmpl.render(**ctx), self._force):
                    generated.append(path)

            # HPA (if prod or heavy scale)
            if svc.sizing.scale in ("prod", "heavy") and svc.type == "app":
                tmpl = self.env.get_template("k8s/hpa.yaml.j2")
                path = k8s_dir / f"{svc.name}-hpa.yaml"
                if self._write_if_changed(path, tmpl.render(**ctx), self._force):
                    generated.append(path)

        # Ingress (for app services)
        app_services = [s for s in model.services if s.type == "app" and s.ports]
        if app_services:
            tmpl = self.env.get_template("k8s/ingress.yaml.j2")
            path = k8s_dir / "ingress.yaml"
            if self._write_if_changed(path, tmpl.render(model=model_data, app_services=[_wrap(s.model_dump()) for s in app_services]), self._force):
                generated.append(path)

        # ConfigMap (for ref envs)
        ref_envs = {}
        for svc in model.services:
            for env_name, env_var in svc.env.items():
                if env_var.kind == "ref":
                    ref_envs[env_name] = env_var.ref
        if ref_envs:
            tmpl = self.env.get_template("k8s/configmap.yaml.j2")
            path = k8s_dir / "configmap.yaml"
            if self._write_if_changed(path, tmpl.render(model=model_data, ref_envs=ref_envs), self._force):
                generated.append(path)

        # Secret placeholder (for secret envs)
        secret_envs = {}
        for svc in model.services:
            for env_name, env_var in svc.env.items():
                if env_var.kind == "secret":
                    secret_envs[env_name] = env_var.ref
        if secret_envs:
            tmpl = self.env.get_template("k8s/secret.yaml.j2")
            path = k8s_dir / "secret.yaml"
            if self._write_if_changed(path, tmpl.render(model=model_data, secret_envs=secret_envs), self._force):
                generated.append(path)

        return generated

    # -- CI/CD -------------------------------------------------------------

    def _generate_ci(self, model: InfraModel) -> list[Path]:
        generated: list[Path] = []
        cicd = model.cicd
        model_data = _wrap(model.model_dump())

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
            "app_services": [_wrap(s.model_dump()) for s in app_services],
        }

        for provider in cicd.providers:
            if provider not in _CI_FILE_MAP:
                logger.warning("Unknown CI provider: %s", provider)
                continue
            template_name, output_path = _CI_FILE_MAP[provider]
            tmpl = self.env.get_template(template_name)
            content = tmpl.render(**ctx)
            path = self.repo_path / output_path
            if self._write_if_changed(path, content, self._force):
                generated.append(path)

        return generated

    # -- Helm charts -------------------------------------------------------

    def _generate_helm(self, model: InfraModel) -> list[Path]:
        generated: list[Path] = []
        helm = model.helm
        chart_name = helm.chart_name or model.project_name
        chart_dir = self.repo_path / "helm" / chart_name
        templates_dir = chart_dir / "templates"
        templates_dir.mkdir(parents=True, exist_ok=True)

        model_data = _wrap(model.model_dump())

        # Chart.yaml
        tmpl = self.env.get_template("helm/Chart.yaml.j2")
        path = chart_dir / "Chart.yaml"
        if self._write_if_changed(path, tmpl.render(
            chart_name=chart_name,
            chart_version=helm.chart_version,
            app_version=helm.app_version,
            model=model_data,
        ), self._force):
            generated.append(path)

        # values.yaml
        tmpl = self.env.get_template("helm/values.yaml.j2")
        path = chart_dir / "values.yaml"
        if self._write_if_changed(path, tmpl.render(model=model_data, helm=_wrap(helm.model_dump())), self._force):
            generated.append(path)

        # templates/deployment.yaml
        tmpl = self.env.get_template("helm/templates/deployment.yaml.j2")
        path = templates_dir / "deployment.yaml"
        if self._write_if_changed(path, tmpl.render(model=model_data), self._force):
            generated.append(path)

        # templates/service.yaml
        tmpl = self.env.get_template("helm/templates/service.yaml.j2")
        path = templates_dir / "service.yaml"
        if self._write_if_changed(path, tmpl.render(model=model_data), self._force):
            generated.append(path)

        # templates/ingress.yaml
        tmpl = self.env.get_template("helm/templates/ingress.yaml.j2")
        path = templates_dir / "ingress.yaml"
        if self._write_if_changed(path, tmpl.render(model=model_data), self._force):
            generated.append(path)

        return generated

    # -- IaC / Terraform ---------------------------------------------------

    def _generate_iac(self, model: InfraModel) -> list[Path]:
        generated: list[Path] = []
        iac = model.iac
        model_data = _wrap(model.model_dump())

        if iac.tool != "terraform":
            logger.warning("IaC tool '%s' not yet supported; only 'terraform' is implemented.", iac.tool)
            return generated

        provider = iac.cloud_provider
        template_path = f"iac/terraform/{provider}/main.tf.j2"

        try:
            tmpl = self.env.get_template(template_path)
        except TemplateNotFound:
            logger.warning("No Terraform template for provider '%s'.", provider)
            return generated

        tf_dir = self.repo_path / "terraform"
        tf_dir.mkdir(parents=True, exist_ok=True)

        path = tf_dir / "main.tf"
        if self._write_if_changed(path, tmpl.render(
            model=model_data,
            iac=_wrap(iac.model_dump()),
        ), self._force):
            generated.append(path)

        return generated

    # -- Monitoring --------------------------------------------------------

    def _generate_monitoring(self, model: InfraModel) -> list[Path]:
        generated: list[Path] = []
        mon = model.monitoring
        model_data = _wrap(model.model_dump())
        mon_dir = self.repo_path / "monitoring"
        mon_dir.mkdir(parents=True, exist_ok=True)

        app_services = [s for s in model.services if s.type in ("app", "worker")]

        if mon.prometheus:
            for svc in app_services:
                tmpl = self.env.get_template("monitoring/servicemonitor.yaml.j2")
                ctx = {
                    "model": model_data,
                    "svc": _wrap(svc.model_dump()),
                    "monitoring": _wrap(mon.model_dump()),
                }
                path = mon_dir / f"{svc.name}-servicemonitor.yaml"
                if self._write_if_changed(path, tmpl.render(**ctx), self._force):
                    generated.append(path)

        if mon.alerting:
            tmpl = self.env.get_template("monitoring/alerting-rules.yaml.j2")
            ctx = {
                "model": model_data,
                "app_services": [_wrap(s.model_dump()) for s in app_services],
                "monitoring": _wrap(mon.model_dump()),
                "thresholds": _wrap(mon.alert_thresholds),
            }
            path = mon_dir / "alerting-rules.yaml"
            if self._write_if_changed(path, tmpl.render(**ctx), self._force):
                generated.append(path)

        if mon.grafana:
            tmpl = self.env.get_template("monitoring/grafana-dashboard.json.j2")
            ctx = {
                "model": model_data,
                "app_services": [_wrap(s.model_dump()) for s in app_services],
                "monitoring": _wrap(mon.model_dump()),
                "thresholds": _wrap(mon.alert_thresholds),
            }
            path = mon_dir / "grafana-dashboard.json"
            if self._write_if_changed(path, tmpl.render(**ctx), self._force):
                generated.append(path)

        return generated

    # -- Multi-tenancy -----------------------------------------------------

    def _generate_tenancy(self, model: InfraModel) -> list[Path]:
        generated: list[Path] = []
        mt = model.multi_tenancy
        model_data = _wrap(model.model_dump())

        for tenant in mt.tenants:
            ns = tenant.namespace or tenant.name
            tenant_data = _wrap(tenant.model_dump())
            tenant_dir = self.repo_path / "k8s" / "tenants" / ns
            tenant_dir.mkdir(parents=True, exist_ok=True)

            ctx = {
                "model": model_data,
                "tenant": tenant_data,
                "namespace": ns,
                "multi_tenancy": _wrap(mt.model_dump()),
            }

            # Namespace
            tmpl = self.env.get_template("tenancy/namespace.yaml.j2")
            path = tenant_dir / "namespace.yaml"
            if self._write_if_changed(path, tmpl.render(**ctx), self._force):
                generated.append(path)

            # ResourceQuota
            tmpl = self.env.get_template("tenancy/resource-quota.yaml.j2")
            path = tenant_dir / "resource-quota.yaml"
            if self._write_if_changed(path, tmpl.render(**ctx), self._force):
                generated.append(path)

            # NetworkPolicy
            if mt.network_policies:
                tmpl = self.env.get_template("tenancy/network-policy.yaml.j2")
                path = tenant_dir / "network-policy.yaml"
                if self._write_if_changed(path, tmpl.render(**ctx), self._force):
                    generated.append(path)

        return generated

    # -- Helpers -----------------------------------------------------------

    @staticmethod
    def _service_context(model: InfraModel, svc) -> dict:
        """Build a template context dict for a single service."""
        model_data = _wrap(model.model_dump())
        svc_data = _wrap(svc.model_dump())
        return {
            "model": model_data,
            "svc": svc_data,
        }
