"""Deterministic development plans for the supported language detectors."""

from __future__ import annotations

import re
import shlex

from ai_infra.models.infra_model import InfraModel


def build_offline_model(analyzer_output: dict) -> InfraModel:
    """Build a validated model without reading files, hints or calling a backend."""
    language = analyzer_output.get("language")
    framework = analyzer_output.get("framework")
    entrypoint = analyzer_output.get("entrypoint")
    default_ports = {"flask": 5000, "node": 3000, "go": 8080}
    port = analyzer_output.get("detected_port")
    if not isinstance(port, int) or not 1 <= port <= 65535:
        port = default_ports.get(framework, default_ports.get(language, 8000))

    if language == "python":
        image = "python:3.11-slim"
        module = (entrypoint or "main.py").removesuffix(".py").replace("/", ".")
        if framework in ("fastapi", "starlette"):
            command = f"uvicorn {shlex.quote(module + ':app')} --host 0.0.0.0 --port {port}"
        elif framework == "flask":
            command = f"flask --app {shlex.quote(module)} run --host=0.0.0.0 --port={port}"
        elif framework == "django":
            command = f"python {shlex.quote(entrypoint or 'manage.py')} runserver 0.0.0.0:{port}"
        else:
            command = f"python {shlex.quote(entrypoint or 'main.py')}"
    elif language == "node":
        image = "node:22-alpine"
        command = "npm start" if framework in ("next", "nest") or not entrypoint else f"node {shlex.quote(entrypoint)}"
    elif language == "go":
        version = analyzer_output.get("go_version") or "1.23"
        if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", version):
            version = "1.23"
        image = f"golang:{version}-alpine"
        command = "/server"
    else:
        raise RuntimeError("Offline planning requires a detected Python, Node.js or Go project.")

    name = analyzer_output.get("project_name") or framework or language
    name = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")[:40].rstrip("-") or "app"
    app = {
        "name": "web",
        "type": "app",
        "image": image,
        "entrypoint": command,
        "ports": [{"container": port, "host": port, "host_ip": "127.0.0.1"}],
        "depends_on": [],
        "env": {"PORT": {"kind": "literal", "value": str(port)}},
    }
    services = [app]
    inferred = set(analyzer_output.get("dependencies", {}).get("inferred_services", []))

    def add_service(name: str, image: str, port: int, volume: str, mount: str, env: dict, app_env: dict) -> None:
        services.append({
            "name": name,
            "type": "cache" if name == "redis" else "database",
            "image": image,
            "ports": [{"container": port, "host": None}],
            "volumes": [{"name": volume, "mount_path": mount}],
            "env": env,
        })
        app["depends_on"].append(name)
        app["env"].update(app_env)

    def literal(value: str) -> dict:
        return {"kind": "literal", "value": value}

    def secret(ref: str) -> dict:
        return {"kind": "secret", "ref": ref}

    if "postgres" in inferred:
        add_service("postgres", "postgres:16-alpine", 5432, "pgdata", "/var/lib/postgresql/data", {
            "POSTGRES_DB": literal("app"), "POSTGRES_USER": literal("app"),
            "POSTGRES_PASSWORD": secret("POSTGRES_PASSWORD"),
        }, {"DATABASE_URL": secret("DATABASE_URL")})
    if "mysql" in inferred:
        add_service("mysql", "mysql:8.4", 3306, "mysqldata", "/var/lib/mysql", {
            "MYSQL_DATABASE": literal("app"), "MYSQL_USER": literal("app"),
            "MYSQL_PASSWORD": secret("MYSQL_PASSWORD"), "MYSQL_ROOT_PASSWORD": secret("MYSQL_ROOT_PASSWORD"),
        }, {"MYSQL_URL": secret("MYSQL_URL")})
    if "mongodb" in inferred:
        add_service("mongodb", "mongo:7", 27017, "mongodata", "/data/db", {
            "MONGO_INITDB_ROOT_USERNAME": literal("app"),
            "MONGO_INITDB_ROOT_PASSWORD": secret("MONGO_INITDB_ROOT_PASSWORD"),
        }, {"MONGODB_URL": secret("MONGODB_URL")})
    if "redis" in inferred:
        add_service("redis", "redis:7-alpine", 6379, "redisdata", "/data", {}, {
            "REDIS_URL": literal("redis://redis:6379/0"),
        })

    return InfraModel.model_validate({
        "project_name": name,
        "routing": {"domain": f"{name}.localhost"},
        "services": services,
        "cluster_assumptions": {"tls_enabled": False, "cert_manager": False},
        "cicd": {"providers": [], "auto_deploy": False},
    })
