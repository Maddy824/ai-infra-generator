"""Planner -- orchestrates LLM calls to produce a validated InfraModel."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from pydantic import ValidationError

from ai_infra.config.settings import settings
from ai_infra.models.infra_model import InfraModel
from ai_infra.planner.prompts import (
    PLAN_PROMPT,
    PLAN_SUMMARY_TEMPLATE,
    REPAIR_PROMPT,
    SYSTEM_PROMPT,
)
from ai_infra.state.state_manager import StateManager

logger = logging.getLogger(__name__)


class Planner:
    """Generate an InfraModel from analyzer output + user hints via LLM.

    The flow is:
    1. Build a prompt from analyzer output, hints, and the InfraModel JSON schema.
    2. Call the configured LLM backend.
    3. Parse + validate the JSON response into a Pydantic InfraModel.
    4. On validation failure, send a repair prompt and retry (up to ``LLM_MAX_RETRIES``).
    5. Write the validated model and a human-readable summary atomically to ``.ai-infra/``.
    """

    def __init__(self, repo_path: Path) -> None:
        self.repo_path = Path(repo_path).resolve()
        self.state = StateManager(self.repo_path)

    # -- public API --------------------------------------------------------

    def plan(self, analyzer_output: dict) -> InfraModel:
        """Run the planning pipeline and return a validated InfraModel.

        On success the model and plan summary are persisted to ``.ai-infra/``.
        On failure (even after retries) a ``RuntimeError`` is raised and the
        previous state is left untouched.
        """
        self.state.init_state_dir()

        # Read optional user hints
        hints = self.state.read_hints()

        # Build the InfraModel JSON schema for the LLM
        schema = InfraModel.model_json_schema()

        prompt = PLAN_PROMPT.format(
            analyzer_output=json.dumps(analyzer_output, indent=2),
            hints=json.dumps(hints, indent=2) if hints else "No user hints provided.",
            schema=json.dumps(schema, indent=2),
        )

        # Call LLM with retry
        model = self._call_llm_with_retry(prompt)

        # Write outputs only after successful validation
        self.state.write_infra_model(model)
        self.state.write_plan_summary(self._format_summary(model))

        return model

    # -- LLM interaction ---------------------------------------------------

    def _call_llm_with_retry(self, prompt: str) -> InfraModel:
        """Call the LLM and retry with repair prompts on validation failure."""
        last_error: ValidationError | None = None

        for attempt in range(settings.LLM_MAX_RETRIES + 1):
            if attempt == 0:
                raw = self._call_llm(SYSTEM_PROMPT, prompt)
            else:
                logger.warning(
                    "Attempt %d/%d — sending repair prompt.",
                    attempt + 1,
                    settings.LLM_MAX_RETRIES + 1,
                )
                repair = REPAIR_PROMPT.format(
                    validation_error=str(last_error),
                    original_prompt=prompt,
                )
                raw = self._call_llm(SYSTEM_PROMPT, repair)

            try:
                cleaned = self._clean_json(raw)
                model = InfraModel.model_validate_json(cleaned)
                return model
            except ValidationError as exc:
                last_error = exc
                logger.warning("Validation failed on attempt %d: %s", attempt + 1, exc)

        raise RuntimeError(
            f"Planner failed after {settings.LLM_MAX_RETRIES + 1} attempts. "
            f"Last validation error: {last_error}"
        )

    def _call_llm(self, system: str, user: str) -> str:
        """Call the configured LLM backend.

        Raises :class:`RuntimeError` immediately on network or API errors so
        that partial / corrupt state is never written to disk.
        """
        if settings.LLM_BACKEND == "ollama":
            return self._call_ollama(system, user)
        elif settings.LLM_BACKEND == "claude":
            return self._call_claude(system, user)
        elif settings.LLM_BACKEND == "openai":
            return self._call_openai(system, user)
        elif settings.LLM_BACKEND == "gemini":
            return self._call_gemini(system, user)
        else:
            raise ValueError(f"Unknown LLM backend: {settings.LLM_BACKEND}")

    def _call_ollama(self, system: str, user: str) -> str:
        """Call Ollama API."""
        import httpx

        try:
            response = httpx.post(
                f"{settings.OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": settings.OLLAMA_MODEL,
                    "system": system,
                    "prompt": user,
                    "stream": False,
                },
                timeout=settings.LLM_TIMEOUT,
            )
            response.raise_for_status()
            return response.json()["response"]
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"Ollama request timed out after {settings.LLM_TIMEOUT}s. "
                f"Is Ollama running at {settings.OLLAMA_BASE_URL}?"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Ollama returned HTTP {exc.response.status_code}: "
                f"{exc.response.text[:500]}"
            ) from exc
        except httpx.ConnectError as exc:
            raise RuntimeError(
                f"Cannot connect to Ollama at {settings.OLLAMA_BASE_URL}. "
                f"Is the Ollama server running?"
            ) from exc

    def _call_claude(self, system: str, user: str) -> str:
        """Call Claude API via httpx."""
        import httpx

        if not settings.CLAUDE_API_KEY:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Configure it to use the Claude backend."
            )

        try:
            response = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.CLAUDE_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": settings.CLAUDE_MODEL,
                    "max_tokens": 4096,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
                timeout=settings.LLM_TIMEOUT,
            )
            response.raise_for_status()
            return response.json()["content"][0]["text"]
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"Claude API request timed out after {settings.LLM_TIMEOUT}s."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Claude API returned HTTP {exc.response.status_code}: "
                f"{exc.response.text[:500]}"
            ) from exc
        except httpx.ConnectError as exc:
            raise RuntimeError(
                "Cannot connect to the Claude API. Check your network connection."
            ) from exc

    def _call_openai(self, system: str, user: str) -> str:
        """Call OpenAI-compatible chat completions API."""
        import httpx

        if not settings.OPENAI_API_KEY:
            raise RuntimeError(
                "OPENAI_API_KEY not set. Configure it to use the OpenAI backend."
            )

        try:
            response = httpx.post(
                f"{settings.OPENAI_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.OPENAI_MODEL,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.2,
                },
                timeout=settings.LLM_TIMEOUT,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"OpenAI request timed out after {settings.LLM_TIMEOUT}s."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"OpenAI API returned HTTP {exc.response.status_code}: "
                f"{exc.response.text[:500]}"
            ) from exc
        except httpx.ConnectError as exc:
            raise RuntimeError(
                f"Cannot connect to OpenAI API at {settings.OPENAI_BASE_URL}. "
                f"Check your network connection."
            ) from exc

    def _call_gemini(self, system: str, user: str) -> str:
        """Call Google Gemini generateContent API."""
        import httpx

        if not settings.GEMINI_API_KEY:
            raise RuntimeError(
                "GEMINI_API_KEY not set. Configure it to use the Gemini backend."
            )

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{settings.GEMINI_MODEL}:generateContent"
            f"?key={settings.GEMINI_API_KEY}"
        )

        try:
            response = httpx.post(
                url,
                headers={"Content-Type": "application/json"},
                json={
                    "system_instruction": {
                        "parts": [{"text": system}],
                    },
                    "contents": [
                        {"role": "user", "parts": [{"text": user}]},
                    ],
                    "generationConfig": {
                        "temperature": 0.2,
                    },
                },
                timeout=settings.LLM_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"Gemini request timed out after {settings.LLM_TIMEOUT}s."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Gemini API returned HTTP {exc.response.status_code}: "
                f"{exc.response.text[:500]}"
            ) from exc
        except httpx.ConnectError as exc:
            raise RuntimeError(
                "Cannot connect to the Gemini API. Check your network connection."
            ) from exc

    # -- output helpers ----------------------------------------------------

    @staticmethod
    def _clean_json(raw: str) -> str:
        """Strip markdown code fences and surrounding whitespace.

        Handles patterns like:
        - ````` ```json ... ``` `````
        - ````` ``` ... ``` `````
        - Leading/trailing whitespace or newlines
        """
        text = raw.strip()
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
        return text.strip()

    @staticmethod
    def _format_summary(model: InfraModel) -> str:
        """Render a human-readable plan summary from the model."""
        # Build services summary
        lines: list[str] = []
        for svc in model.services:
            ports = ", ".join(f"{p.container}" for p in svc.ports) if svc.ports else "none"
            lines.append(f"- **{svc.name}** ({svc.type}) — image: `{svc.image}`, ports: {ports}")
        services_summary = "\n".join(lines)

        # Build env summary
        env_lines: list[str] = []
        for svc in model.services:
            for env_name, env_var in svc.env.items():
                env_lines.append(f"- `{svc.name}.{env_name}` → {env_var.kind}")
        env_summary = "\n".join(env_lines) if env_lines else "- No environment variables detected."

        # Determine scale (use first service's scale as representative)
        scale = model.services[0].sizing.scale if model.services else "dev"

        # Build CI/CD summary
        cicd_providers = ", ".join(model.cicd.providers)
        cicd_registry = model.cicd.registry
        cicd_auto_deploy = str(model.cicd.auto_deploy)

        # Build enterprise feature status lines
        helm_status = "Enabled" if model.helm.enabled else "Disabled"
        if model.helm.enabled and model.helm.chart_name:
            helm_status += f" (chart: {model.helm.chart_name})"

        if model.iac.enabled:
            iac_status = f"Enabled ({model.iac.cloud_provider.upper()} / {model.iac.tool}, region: {model.iac.region})"
        else:
            iac_status = "Disabled"

        monitoring_status = "Enabled" if model.monitoring.enabled else "Disabled"
        if model.monitoring.enabled:
            parts = []
            if model.monitoring.prometheus:
                parts.append("Prometheus")
            if model.monitoring.grafana:
                parts.append("Grafana")
            if model.monitoring.alerting:
                parts.append("Alerting")
            monitoring_status += f" ({', '.join(parts)})"

        if model.multi_tenancy.enabled:
            tenant_names = [t.name for t in model.multi_tenancy.tenants]
            tenancy_status = f"Enabled ({len(tenant_names)} tenant(s): {', '.join(tenant_names)})"
        else:
            tenancy_status = "Disabled"

        # Build suggestions
        suggestions: list[str] = []
        if model.capabilities.needs_gpu:
            suggestions.append("- GPU-enabled node pool required for scheduling.")
        if model.cluster_assumptions.tls_enabled and model.cluster_assumptions.cert_manager:
            suggestions.append("- cert-manager will handle TLS certificate provisioning.")
        if any(svc.sizing.scale == "dev" for svc in model.services):
            suggestions.append(
                "- Running in **dev** scale. Consider `scale: prod` for production deployments."
            )
        if not suggestions:
            suggestions.append("- No additional suggestions.")

        return PLAN_SUMMARY_TEMPLATE.format(
            project_name=model.project_name,
            services_summary=services_summary,
            scale=scale,
            ingress_controller=model.cluster_assumptions.ingress_controller,
            tls_enabled=model.cluster_assumptions.tls_enabled,
            cicd_providers=cicd_providers,
            cicd_registry=cicd_registry,
            cicd_auto_deploy=cicd_auto_deploy,
            helm_status=helm_status,
            iac_status=iac_status,
            monitoring_status=monitoring_status,
            tenancy_status=tenancy_status,
            env_summary=env_summary,
            suggestions="\n".join(suggestions),
        )
