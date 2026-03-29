"""Go module detector."""

from __future__ import annotations

import re
from pathlib import Path

from ai_infra.analyzer.detectors.base import BaseDetector
from ai_infra.config.settings import settings

_DEP_SERVICE_MAP: dict[str, str] = {
    "github.com/jackc/pgx": "postgres",
    "github.com/lib/pq": "postgres",
    "github.com/go-redis/redis": "redis",
    "github.com/redis/go-redis": "redis",
    "go.mongodb.org/mongo-driver": "mongodb",
}

_FRAMEWORK_MAP: dict[str, str] = {
    "github.com/gin-gonic/gin": "gin",
    "github.com/gorilla/mux": "gorilla/mux",
    "github.com/labstack/echo": "echo",
    "github.com/gofiber/fiber": "fiber",
    "github.com/go-chi/chi": "chi",
}

_PORT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r'http\.ListenAndServe\s*\(\s*"(?::)?(\d+)"'),
    re.compile(r'ListenAndServe\s*\(\s*"(?::)?(\d+)"'),
    re.compile(r'\.Start\s*\(\s*"(?::)?(\d+)"'),
    re.compile(r'\.Run\s*\(\s*"(?::)?(\d+)"'),
    re.compile(r'Addr\s*(?:=|:)\s*"(?::)?(\d+)"'),
    re.compile(r'Listen\s*\(\s*"(?::)?(\d+)"'),
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


class GoDetector(BaseDetector):
    def matches(self, repo_path: Path) -> bool:
        return (repo_path / "go.mod").is_file()

    def detect(self, repo_path: Path) -> dict | None:
        if not self.matches(repo_path):
            return None
        go_mod = _safe_read(repo_path / "go.mod")
        if go_mod is None:
            return None
        module_name, go_version = self._parse_go_mod_header(go_mod)
        raw_deps = self._parse_go_mod_requires(go_mod)
        dep_paths = [d for d, _ in raw_deps]
        framework = self._detect_framework(dep_paths)
        entrypoint = self._detect_entrypoint(repo_path)
        detected_port = self._detect_port(repo_path, entrypoint)
        inferred = self._infer_services(dep_paths)
        infra_files = self._check_existing_infra(repo_path)
        return {
            "language": "go",
            "framework": framework,
            "entrypoint": entrypoint,
            "detected_port": detected_port,
            "go_module": module_name,
            "go_version": go_version,
            "dependencies": {
                "raw": [f"{mod}@{ver}" for mod, ver in raw_deps],
                "inferred_services": inferred,
            },
            "existing_infra_files": infra_files,
        }

    @staticmethod
    def _parse_go_mod_header(content: str) -> tuple[str | None, str | None]:
        module_name: str | None = None
        go_version: str | None = None
        for line in content.splitlines():
            line = line.strip()
            m = re.match(r"^module\s+(\S+)", line)
            if m:
                module_name = m.group(1)
            m = re.match(r"^go\s+(\S+)", line)
            if m:
                go_version = m.group(1)
        return module_name, go_version

    @staticmethod
    def _parse_go_mod_requires(content: str) -> list[tuple[str, str]]:
        deps: list[tuple[str, str]] = []
        block_pattern = re.compile(r"require\s*\((.*?)\)", re.DOTALL)
        for block in block_pattern.findall(content):
            for line in block.splitlines():
                line = line.strip()
                if not line or line.startswith("//"):
                    continue
                if "// indirect" in line:
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    deps.append((parts[0], parts[1]))
        single_pattern = re.compile(r"^require\s+(\S+)\s+(\S+)", re.MULTILINE)
        for m in single_pattern.finditer(content):
            dep = (m.group(1), m.group(2))
            if dep not in deps:
                deps.append(dep)
        return deps

    @staticmethod
    def _detect_framework(dep_paths: list[str]) -> str | None:
        for dep in dep_paths:
            for mod_prefix, name in _FRAMEWORK_MAP.items():
                if dep == mod_prefix or dep.startswith(mod_prefix + "/"):
                    return name
        return None

    @staticmethod
    def _detect_entrypoint(repo_path: Path) -> str | None:
        if (repo_path / "main.go").is_file():
            return "main.go"
        cmd_dir = repo_path / "cmd"
        if cmd_dir.is_dir():
            try:
                for sub in sorted(cmd_dir.iterdir()):
                    if sub.is_dir():
                        main_go = sub / "main.go"
                        if main_go.is_file():
                            return str(main_go.relative_to(repo_path))
            except OSError:
                pass
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
    def _infer_services(dep_paths: list[str]) -> list[str]:
        services: set[str] = set()
        for dep in dep_paths:
            for mod_prefix, svc in _DEP_SERVICE_MAP.items():
                if dep == mod_prefix or dep.startswith(mod_prefix + "/"):
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
