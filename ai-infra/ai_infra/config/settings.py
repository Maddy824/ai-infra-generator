"""Centralized configuration for ai-infra.

This is the ONLY module that reads environment variables or sets defaults.
Every other module should import from ``ai_infra.config.settings``.

Usage::

    from ai_infra.config.settings import settings

    url = settings.OLLAMA_BASE_URL
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AiInfraSettings(BaseSettings):
    """Application settings loaded from environment variables.

    Variables are read with the ``AI_INFRA_`` prefix unless a different
    ``validation_alias`` / ``env`` is specified on the field.
    """

    model_config = SettingsConfigDict(
        env_prefix="AI_INFRA_",
        # Allow extra env vars without raising an error
        extra="ignore",
    )

    # ── LLM backend selection ───────────────────────────────────────────
    LLM_BACKEND: Literal["ollama", "claude", "openai", "gemini"] = Field(
        default="ollama",
        description='Which LLM backend to use: "ollama", "claude", "openai", or "gemini".',
    )

    # ── Ollama settings ─────────────────────────────────────────────────
    OLLAMA_URL: str = Field(
        default="http://localhost:11434",
        description="Base URL for the Ollama API.",
    )
    OLLAMA_MODEL: str = Field(
        default="qwen2.5-coder:7b",
        description="Ollama model to use for inference.",
    )

    # ── Claude / Anthropic settings ─────────────────────────────────────
    CLAUDE_API_KEY: Optional[str] = Field(
        default=None,
        validation_alias="ANTHROPIC_API_KEY",
        description="Anthropic API key (read from ANTHROPIC_API_KEY env var).",
    )
    CLAUDE_MODEL: str = Field(
        default="claude-sonnet-4-20250514",
        description="Claude model to use for inference.",
    )

    # ── OpenAI settings ────────────────────────────────────────────────
    OPENAI_API_KEY: Optional[str] = Field(
        default=None,
        validation_alias="OPENAI_API_KEY",
        description="OpenAI API key (read from OPENAI_API_KEY env var).",
    )
    OPENAI_MODEL: str = Field(
        default="gpt-4o",
        description="OpenAI model to use for inference.",
    )
    OPENAI_BASE_URL: str = Field(
        default="https://api.openai.com/v1",
        description="OpenAI-compatible API base URL. Override for Azure OpenAI or local proxies.",
    )

    # ── Gemini / Google settings ───────────────────────────────────────
    GEMINI_API_KEY: Optional[str] = Field(
        default=None,
        validation_alias="GEMINI_API_KEY",
        description="Google Gemini API key (read from GEMINI_API_KEY env var).",
    )
    GEMINI_MODEL: str = Field(
        default="gemini-2.0-flash",
        description="Gemini model to use for inference.",
    )

    # ── General LLM behaviour ──────────────────────────────────────────
    LLM_TIMEOUT: int = Field(
        default=120,
        description="Timeout in seconds for LLM requests.",
    )
    LLM_MAX_RETRIES: int = Field(
        default=2,
        description="Maximum number of retries for failed LLM requests.",
    )

    # ── Repository / state ──────────────────────────────────────────────
    STATE_DIR_NAME: str = Field(
        default=".ai-infra",
        description="Directory name created inside repos to store ai-infra state.",
    )

    # ── Analyzer limits ─────────────────────────────────────────────────
    ANALYZER_MAX_FILE_SIZE: int = Field(
        default=1_048_576,
        description="Files larger than this (in bytes) are skipped by the analyzer.",
    )
    ANALYZER_TIMEOUT: int = Field(
        default=60,
        description="Timeout in seconds for analyzer operations.",
    )

    # ── Convenience properties ──────────────────────────────────────────

    @property
    def OLLAMA_BASE_URL(self) -> str:
        """Alias kept for readability — maps to the OLLAMA_URL field."""
        return self.OLLAMA_URL


# ── Singleton instance ──────────────────────────────────────────────────
settings = AiInfraSettings()
