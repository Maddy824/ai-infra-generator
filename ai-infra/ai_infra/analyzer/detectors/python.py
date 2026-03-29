"""Python / pip / pyproject detector."""

from __future__ import annotations

import re
from pathlib import Path

from ai_infra.analyzer.detectors.base import BaseDetector
from ai_infra.config.settings import settings

# ---------------------------------------------------------------------------
# Dependency -> inferred service mapping
# ---------------------------------------------------------------------------

_DEP_SERVICE_MAP: dict[str, str] = {
    "psycopg2": "postgres",
    "psycopg2-binary": "postgres",
    "asyncpg": "postgres",
    "redis": "redis",
    "aioredis": "redis",
    "celery": "worker",
    "boto3": "s3",
    "botocore": "s3",
    "pymongo": "mongodb",
    "motor": "mongodb",
}

# sqlalchemy itself doesn't pick a DB; look for specific driver packages
_SQLALCHEMY_DRIVER_MAP: dict[str, str] = {
    "psycopg2": "postgres",
    "psycopg2-binary": "postgres",
    "asyncpg": "postgres",
    "pymysql": "mysql",
    "mysqlclient": "mysql",
    "aiomysql": "mysql",
    "aiosqlite": "sqlite",
    "cx_oracle": "oracle",
    "oracledb": "oracle",
}

_FRAMEWORK_PACKAGES = ("fastapi", "flask", "django", "starlette")

_ENTRYPOINT_CANDIDATES = ("main.py", "app.py", "manage.py", "wsgi.py", "asgi.py")

# Regex patterns for port detection
_PORT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"uvicorn\.run\s*\(.*?port\s*=\s*(\d+)", re.DOTALL),
    re.compile(r"app\.run\s*\(.*?port\s*=\s*(\d+)", re.DOTALL),
    re.compile(r"\.run\s*\(.*?port\s*=\s*(\d+)", re.DOTALL),
    re.compile(r"""['"]--port['"]\s*,\s*['"](\d+)['"]"""),
    re.compile(r"--port\s+(\d+)"),
    re.compile(r"PORT\s*=\s*(\d+)"),
]


def _safe_read(path: Path) -> str | None:
    """Read a file if it exists and is within the size limit."""
    try:
        if not path.is_file():
            return None
        if path.stat().st_size > settings.ANALYZER_MAX_FILE_SIZE:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _strip_version(dep: str) -> str:
    """Strip version specifiers from a dependency string.

    Examples:
        'requests>=2.28,<3'  -> 'requests'
        'uvicorn[standard]'  -> 'uvicorn'
        'numpy ==1.24.0'     -> 'numpy'
    """
    # Remove extras like [standard]
    name = re.split(r"[\[;@]", dep, maxsplit=1)[0]
    # Remove version specifiers
    name = re.split(r"[><=!~\s]", name, maxsplit=1)[0]
    return name.strip().lower()


class PythonDetector(BaseDetector):
    """Detect Python projects and their frameworks/dependencies."""

    # -- BaseDetector interface ------------------------------------------------

    def matches(self, repo_path: Path) -> bool:
        markers = ("requirements.txt", "pyproject.toml", "setup.py", "Pipfile")
        return any((repo_path / m).is_file() for m in markers)

    def detect(self, repo_path: Path) -> dict | None:
        if not self.matches(repo_path):
            return None

        raw_deps = self._collect_deps(repo_path)
        dep_names = [_strip_version(d) for d in raw_deps]

        framework = self._detect_framework(dep_names)
        entrypoint = self._detect_entrypoint(repo_path, framework)
        detected_port = self._detect_port(repo_path, entrypoint)
        inferred = self._infer_services(dep_names)
        infra_files = self._check_existing_infra(repo_path)

        return {
            "language": "python",
            "framework": framework,
            "entrypoint": entrypoint,
            "detected_port": detected_port,
            "dependencies": {
                "raw": raw_deps,
                "inferred_services": inferred,
            },
            "existing_infra_files": infra_files,
        }

    # -- Internal helpers ------------------------------------------------------

    def _collect_deps(self, repo_path: Path) -> list[str]:
        """Gather dependencies from requirements.txt and/or pyproject.toml."""
        deps: list[str] = []

        # requirements.txt
        req_txt = _safe_read(repo_path / "requirements.txt")
        if req_txt is not None:
            for line in req_txt.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-"):
                    continue
                deps.append(line)

        # pyproject.toml [project.dependencies]
        pyproject_path = repo_path / "pyproject.toml"
        pyproject_txt = _safe_read(pyproject_path)
        if pyproject_txt is not None:
            try:
                import tomllib

                data = tomllib.loads(pyproject_txt)
                project_deps = data.get("project", {}).get("dependencies", [])
                if isinstance(project_deps, list):
                    deps.extend(project_deps)
            except Exception:  # noqa: BLE001
                pass

        return deps

    @staticmethod
    def _detect_framework(dep_names: list[str]) -> str | None:
        for fw in _FRAMEWORK_PACKAGES:
            if fw in dep_names:
                return fw
        return None

    @staticmethod
    def _detect_entrypoint(repo_path: Path, framework: str | None) -> str | None:
        # Django has a clear entrypoint
        if framework == "django":
            manage = repo_path / "manage.py"
            if manage.is_file():
                return "manage.py"

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
        has_sqlalchemy = "sqlalchemy" in dep_names

        for dep in dep_names:
            if dep in _DEP_SERVICE_MAP:
                services.add(_DEP_SERVICE_MAP[dep])
            # If sqlalchemy is present, check driver packages
            if has_sqlalchemy and dep in _SQLALCHEMY_DRIVER_MAP:
                services.add(_SQLALCHEMY_DRIVER_MAP[dep])

        # If sqlalchemy is present but no specific driver was found, don't assume
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
