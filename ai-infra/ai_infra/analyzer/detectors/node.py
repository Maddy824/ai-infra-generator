"""Node.js / npm / yarn detector."""

from __future__ import annotations

import json
import re
from pathlib import Path

from ai_infra.analyzer.detectors.base import BaseDetector
from ai_infra.config.settings import settings

_DEP_SERVICE_MAP: dict[str, str] = {
    "pg": "postgres",
    "pg-pool": "postgres",
    "knex": "postgres",
    "redis": "redis",
    "ioredis": "redis",
    "bullmq": "worker",
    "bull": "worker",
    "mongoose": "mongodb",
    "mongodb": "mongodb",
    "aws-sdk": "s3",
    "@aws-sdk/client-s3": "s3",
}

_DEP_PREFIX_SERVICE: list[tuple[str, str]] = [
    ("@aws-sdk/", "s3"),
]

_FRAMEWORK_PACKAGES = ("express", "next", "@nestjs/core", "koa", "fastify")
_FRAMEWORK_NAMES: dict[str, str] = {
    "express": "express",
    "next": "next",
    "@nestjs/core": "nest",
    "koa": "koa",
    "fastify": "fastify",
}

_ENTRYPOINT_CANDIDATES = ("index.js", "server.js", "app.js", "src/index.ts", "src/index.js")

_PORT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\.listen\s*\(\s*(\d+)"),
    re.compile(r"\.listen\s*\(\s*(?:process\.env\.PORT\s*\|\|\s*)(\d+)"),
    re.compile(r"PORT\s*(?:=|:)\s*(\d+)"),
    re.compile(r"port\s*(?:=|:)\s*(\d+)"),
]


def _safe_read(path: Path) -> str | None:
    try:
        if not path.is_file():
            return None
        if path.stat().st_size > settings.ANALYZER_MAX_FILE_SIZE:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


class NodeDetector(BaseDetector):
    def matches(self, repo_path: Path) -> bool:
        return (repo_path / "package.json").is_file()

    def detect(self, repo_path: Path) -> dict | None:
        if not self.matches(repo_path):
            return None
        pkg = self._parse_package_json(repo_path)
        if pkg is None:
            return None
        all_deps = self._collect_deps(pkg)
        dep_names = list(all_deps.keys())
        framework = self._detect_framework(dep_names)
        entrypoint = self._detect_entrypoint(repo_path, pkg)
        detected_port = self._detect_port(repo_path, entrypoint)
        inferred = self._infer_services(dep_names)
        infra_files = self._check_existing_infra(repo_path)
        return {
            "language": "node",
            "framework": framework,
            "entrypoint": entrypoint,
            "detected_port": detected_port,
            "dependencies": {"raw": dep_names, "inferred_services": inferred},
            "existing_infra_files": infra_files,
        }

    @staticmethod
    def _parse_package_json(repo_path: Path) -> dict | None:
        content = _safe_read(repo_path / "package.json")
        if content is None:
            return None
        try:
            return json.loads(content)
        except (json.JSONDecodeError, ValueError):
            return None

    @staticmethod
    def _collect_deps(pkg: dict) -> dict[str, str]:
        deps: dict[str, str] = {}
        for key in ("dependencies", "devDependencies"):
            section = pkg.get(key)
            if isinstance(section, dict):
                deps.update(section)
        return deps

    @staticmethod
    def _detect_framework(dep_names: list[str]) -> str | None:
        for pkg_name in _FRAMEWORK_PACKAGES:
            if pkg_name in dep_names:
                return _FRAMEWORK_NAMES[pkg_name]
        return None

    @staticmethod
    def _detect_entrypoint(repo_path: Path, pkg: dict) -> str | None:
        main = pkg.get("main")
        if isinstance(main, str) and (repo_path / main).is_file():
            return main
        for candidate in _ENTRYPOINT_CANDIDATES:
            if (repo_path / candidate).is_file():
                return candidate
        return None

    @staticmethod
    def _detect_port(repo_path: Path, entrypoint: str | None) -> int | None:
        if entrypoint is None:
            return None
        content = _safe_read(repo_path / entrypoint)
        if content is None:
            return None
        for pat in _PORT_PATTERNS:
            m = pat.search(content)
            if m:
                try:
                    port = int(m.group(1))
                    if 1 <= port <= 65535:
                        return port
                except ValueError:
                    continue
        return None

    @staticmethod
    def _infer_services(dep_names: list[str]) -> list[str]:
        services: set[str] = set()
        for dep in dep_names:
            if dep in _DEP_SERVICE_MAP:
                services.add(_DEP_SERVICE_MAP[dep])
            for prefix, svc in _DEP_PREFIX_SERVICE:
                if dep.startswith(prefix):
                    services.add(svc)
        return sorted(services)

    @staticmethod
    def _check_existing_infra(repo_path: Path) -> list[str]:
        found: list[str] = []
        if (repo_path / "Dockerfile").is_file():
            found.append("Dockerfile")
        if (repo_path / "docker-compose.yml").is_file():
            found.append("docker-compose.yml")
        if (repo_path / "docker-compose.yaml").is_file():
            found.append("docker-compose.yaml")
        return found
