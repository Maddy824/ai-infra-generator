"""Analyzer orchestrator -- discovers detectors, runs them, and merges results."""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
import re
from pathlib import Path

import ai_infra.analyzer.detectors as _detectors_pkg
from ai_infra.analyzer.detectors.base import BaseDetector
from ai_infra.config.settings import settings
from ai_infra.state.state_manager import StateManager

logger = logging.getLogger(__name__)


def _discover_detectors() -> list[BaseDetector]:
    detectors: list[BaseDetector] = []
    package_path = _detectors_pkg.__path__
    prefix = _detectors_pkg.__name__ + "."
    for finder, module_name, is_pkg in pkgutil.iter_modules(package_path, prefix):
        try:
            module = importlib.import_module(module_name)
        except Exception:
            logger.warning("Failed to import detector module %s", module_name)
            continue
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, BaseDetector) and obj is not BaseDetector:
                detectors.append(obj())
    return detectors


_EXPOSE_RE = re.compile(r"^\s*EXPOSE\s+(\d+)", re.MULTILINE)
_FROM_RE = re.compile(r"^\s*FROM\s+(\S+)", re.MULTILINE)
_CMD_RE = re.compile(r"^\s*(?:CMD|ENTRYPOINT)\s+(.+)$", re.MULTILINE)


def _safe_read(path: Path) -> str | None:
    try:
        if not path.is_file():
            return None
        if path.stat().st_size > settings.ANALYZER_MAX_FILE_SIZE:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _extract_dockerfile_info(repo_path: Path) -> dict | None:
    content = _safe_read(repo_path / "Dockerfile")
    if content is None:
        return None
    info: dict[str, object] = {}
    expose_match = _EXPOSE_RE.search(content)
    if expose_match:
        try:
            info["port"] = int(expose_match.group(1))
        except ValueError:
            pass
    from_matches = _FROM_RE.findall(content)
    if from_matches:
        info["base_image"] = from_matches[-1]
    cmd_match = _CMD_RE.search(content)
    if cmd_match:
        info["entrypoint"] = cmd_match.group(1).strip()
    return info if info else None


def _merge_results(results: list[dict]) -> dict:
    merged: dict[str, object] = {
        "language": None,
        "framework": None,
        "entrypoint": None,
        "detected_port": None,
        "dependencies": {"raw": [], "inferred_services": []},
        "existing_infra_files": [],
    }
    seen_raw: set[str] = set()
    all_services: set[str] = set()
    all_infra: set[str] = set()
    first_value_keys = ("language", "framework", "entrypoint", "detected_port")
    for result in results:
        for key in first_value_keys:
            if merged[key] is None and result.get(key) is not None:
                merged[key] = result[key]
        deps = result.get("dependencies", {})
        for dep in deps.get("raw", []):
            if dep not in seen_raw:
                seen_raw.add(dep)
                merged["dependencies"]["raw"].append(dep)
        for svc in deps.get("inferred_services", []):
            all_services.add(svc)
        for f in result.get("existing_infra_files", []):
            all_infra.add(f)
        for key, value in result.items():
            if key not in merged and key not in ("dependencies", "existing_infra_files"):
                merged[key] = value
    merged["dependencies"]["inferred_services"] = sorted(all_services)
    merged["existing_infra_files"] = sorted(all_infra)
    return merged


def analyze(repo_path: Path) -> dict:
    repo_path = Path(repo_path).resolve()
    detectors = _discover_detectors()
    logger.info("Discovered %d detector(s): %s", len(detectors), [type(d).__name__ for d in detectors])
    results: list[dict] = []
    for detector in detectors:
        try:
            if not detector.matches(repo_path):
                continue
        except Exception:
            logger.warning("Detector %s.matches() raised an exception", type(detector).__name__, exc_info=True)
            continue
        try:
            result = detector.detect(repo_path)
            if result is not None:
                results.append(result)
                logger.info("Detector %s produced a result", type(detector).__name__)
        except Exception:
            logger.warning("Detector %s.detect() raised an exception", type(detector).__name__, exc_info=True)
    if results:
        merged = _merge_results(results)
    else:
        merged = {
            "language": None, "framework": None, "entrypoint": None,
            "detected_port": None,
            "dependencies": {"raw": [], "inferred_services": []},
            "existing_infra_files": [],
        }
    dockerfile_info = _extract_dockerfile_info(repo_path)
    if dockerfile_info is not None:
        merged["dockerfile_info"] = dockerfile_info
        if merged["detected_port"] is None and "port" in dockerfile_info:
            merged["detected_port"] = dockerfile_info["port"]
    state = StateManager(repo_path)
    state.init_state_dir()
    state.write_analyzer_output(merged)
    logger.info("Wrote analyzer output to %s", state.state_dir / "analyzer_output.json")
    return merged
