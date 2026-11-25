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


def contained_path(repo_path: Path, path: Path) -> Path | None:
    """Resolve a candidate only if it stays inside the analyzed repository."""
    try:
        resolved = path.resolve(strict=True)
        return resolved if resolved.is_relative_to(repo_path.resolve()) else None
    except (OSError, RuntimeError, ValueError):
        return None


def repo_file(repo_path: Path, path: Path) -> bool:
    resolved = contained_path(repo_path, path)
    return resolved is not None and resolved.is_file()


def safe_read(repo_path: Path, path: Path) -> str | None:
    """Read a contained regular file within the analyzer size limit."""
    resolved = contained_path(repo_path, path)
    if resolved is None:
        return None
    try:
        if not resolved.is_file() or resolved.stat().st_size > settings.ANALYZER_MAX_FILE_SIZE:
            return None
        return resolved.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def check_existing_infra(repo_path: Path) -> list[str]:
    """Return the container/compose files already present at the repo root."""
    return [name for name in _INFRA_FILES if repo_file(repo_path, repo_path / name)]


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
