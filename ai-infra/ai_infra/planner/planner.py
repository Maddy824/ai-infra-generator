"""Planner -- orchestrates LLM calls to produce a validated InfraModel."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

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

    def _call_llm_with_retry(
        self, prompt: str, system: str = SYSTEM_PROMPT, label: str = "Planner",
    ) -> InfraModel:
        """Call the LLM and retry with repair prompts on validation failure.

        Network / API errors raise :class:`RuntimeError` immediately; only
        invalid or schema-violating responses are retried.
        """
        from rich.console import Console

        console = Console(stderr=True)
        last_error: ValidationError | None = None

        for attempt in range(settings.LLM_MAX_RETRIES + 1):
            if attempt == 0:
                status_msg = f"Calling {settings.LLM_BACKEND} LLM..."
                user = prompt
            else:
                status_msg = f"Retry {attempt}/{settings.LLM_MAX_RETRIES} — sending repair prompt..."
                logger.warning(
                    "Attempt %d/%d — sending repair prompt.",
                    attempt + 1,
                    settings.LLM_MAX_RETRIES + 1,
                )
                user = REPAIR_PROMPT.format(
                    validation_error=str(last_error),
                    original_prompt=prompt,
                )

            with console.status(f"[bold cyan]{status_msg}[/bold cyan]", spinner="dots"):
                raw = self._call_llm(system, user)

            try:
                return InfraModel.model_validate_json(self._clean_json(raw))
            except ValidationError as exc:
                last_error = exc
                logger.warning("Validation failed on attempt %d: %s", attempt + 1, exc)

        raise RuntimeError(
            f"{label} failed after {settings.LLM_MAX_RETRIES + 1} attempts. "
            f"Last validation error: {last_error}"
        )

    def _call_llm(self, system: str, user: str) -> str:
        """Call the configured LLM backend and return the raw text response.

        Raises :class:`RuntimeError` immediately on network or API errors so
        that partial / corrupt state is never written to disk.
        """
        backends = {
            "ollama": self._call_ollama,
            "claude": self._call_claude,
            "openai": self._call_openai,
            "gemini": self._call_gemini,
        }
        try:
            call = backends[settings.LLM_BACKEND]
        except KeyError:
            raise ValueError(f"Unknown LLM backend: {settings.LLM_BACKEND}") from None
        return call(system, user)

    @staticmethod
    def _post_json(name: str, url: str, *, hint: str = "", **kwargs: Any) -> dict:
        """POST to an LLM API and return the decoded JSON body.

        All transport and HTTP failures are converted to :class:`RuntimeError`
        with a message suitable for showing to the user.
        """
        import httpx

        try:
            response = httpx.post(url, timeout=settings.LLM_TIMEOUT, **kwargs)
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"{name} request timed out after {settings.LLM_TIMEOUT}s. {hint}".strip()
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"{name} returned HTTP {exc.response.status_code}: "
                f"{exc.response.text[:500]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Cannot reach {name}: {exc}. {hint}".strip()) from exc
        except ValueError as exc:
            raise RuntimeError(f"{name} returned a non-JSON response.") from exc

    def _call_ollama(self, system: str, user: str) -> str:
        """Call Ollama API."""
        data = self._post_json(
            "Ollama",
            f"{settings.OLLAMA_BASE_URL}/api/generate",
            hint=f"Is Ollama running at {settings.OLLAMA_BASE_URL}?",
            json={
                "model": settings.OLLAMA_MODEL,
                "system": system,
                "prompt": user,
                "stream": False,
                # Constrain decoding to valid JSON -- small local models
                # otherwise often wrap the answer in prose.
                "format": "json",
                "options": {"temperature": 0.2},
            },
        )
        try:
            return data["response"]
        except KeyError as exc:
            raise RuntimeError(f"Unexpected Ollama response: {str(data)[:500]}") from exc

    def _call_claude(self, system: str, user: str) -> str:
        """Call the Claude Messages API via httpx."""
        if not settings.CLAUDE_API_KEY:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Configure it to use the Claude backend."
            )

        headers = {
            "x-api-key": settings.CLAUDE_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        body: dict[str, Any] = {
            "model": settings.CLAUDE_MODEL,
            "max_tokens": settings.LLM_MAX_TOKENS,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if settings.CLAUDE_FALLBACKS:
            headers["anthropic-beta"] = "server-side-fallback-2026-07-01"
            body["fallbacks"] = "default"

        data = self._post_json(
            "Claude API",
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=body,
        )

        stop_reason = data.get("stop_reason")
        if stop_reason == "refusal":
            details = data.get("stop_details") or {}
            raise RuntimeError(
                f"Claude declined the request (category: {details.get('category')})."
            )
        # The response may contain thinking blocks before the answer; only
        # text blocks carry the JSON we asked for.
        text = "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        )
        if stop_reason == "max_tokens":
            logger.warning(
                "Claude response hit max_tokens (%d); output may be truncated. "
                "Raise AI_INFRA_LLM_MAX_TOKENS if this persists.",
                settings.LLM_MAX_TOKENS,
            )
        if not text:
            raise RuntimeError("Claude API returned no text content.")
        return text

    def _call_openai(self, system: str, user: str) -> str:
        """Call OpenAI-compatible chat completions API."""
        if not settings.OPENAI_API_KEY:
            raise RuntimeError(
                "OPENAI_API_KEY not set. Configure it to use the OpenAI backend."
            )

        data = self._post_json(
            "OpenAI API",
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
        )
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected OpenAI response: {str(data)[:500]}") from exc

    def _call_gemini(self, system: str, user: str) -> str:
        """Call Google Gemini generateContent API."""
        if not settings.GEMINI_API_KEY:
            raise RuntimeError(
                "GEMINI_API_KEY not set. Configure it to use the Gemini backend."
            )

        data = self._post_json(
            "Gemini API",
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{settings.GEMINI_MODEL}:generateContent",
            # Send the key as a header rather than a query parameter so it
            # never ends up in URLs printed in error messages or logs.
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": settings.GEMINI_API_KEY,
            },
            json={
                "system_instruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {
                    "temperature": 0.2,
                    "responseMimeType": "application/json",
                },
            },
        )
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected Gemini response: {str(data)[:500]}") from exc

    # -- output helpers ----------------------------------------------------

    @staticmethod
    def _clean_json(raw: str) -> str:
        """Extract the JSON object from an LLM response.

        Handles patterns like:
        - ````` ```json ... ``` ````` (anywhere in the response)
        - Prose before or after the JSON object
        - Leading/trailing whitespace or newlines
        """
        text = raw.strip()
        fenced = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if fenced:
            text = fenced.group(1).strip()
        if not text.startswith("{"):
            first, last = text.find("{"), text.rfind("}")
            if first != -1 and last > first:
                text = text[first : last + 1]
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
