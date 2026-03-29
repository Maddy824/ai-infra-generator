"""Abstract base class for language/framework detectors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


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
