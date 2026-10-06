"""Abstract base class for language/framework detectors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ai_infra.config.settings import settings

# Infra files whose presence is reported in ``existing_infra_files``.
_INFRA_FILES = (
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
)


def safe_read(path: Path) -> str | None:
    """Read a file if it exists and is within the analyzer size limit."""
    try:
        if not path.is_file():
            return None
        if path.stat().st_size > settings.ANALYZER_MAX_FILE_SIZE:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def check_existing_infra(repo_path: Path) -> list[str]:
    """Return the container/compose files already present at the repo root."""
    return [name for name in _INFRA_FILES if (repo_path / name).is_file()]


class BaseDetector(ABC):
    """Base interface for language/framework detectors."""

    @abstractmethod
    def detect(self, repo_path: Path) -> dict | None:
        """Analyze repo and return detection result, or None if not applicable.

        Return dict with keys: language, framework, entrypoint, detected_port,
        dependencies (dict with 'raw' list and 'inferred_services' list),
        existing_infra_files (list).
        """
        ...

    @abstractmethod
    def matches(self, repo_path: Path) -> bool:
        """Return True if this detector is applicable to the repo."""
        ...
