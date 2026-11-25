"""Tests for language/framework detectors."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_infra.analyzer.detectors.go import GoDetector
from ai_infra.analyzer.detectors.node import NodeDetector
from ai_infra.analyzer.detectors.python import PythonDetector

# ---------------------------------------------------------------------------
# Python detector
# ---------------------------------------------------------------------------


class TestPythonDetector:
    def test_matches_requirements_txt(self, fastapi_app_dir: Path):
        d = PythonDetector()
        assert d.matches(fastapi_app_dir)

    def test_detects_fastapi(self, fastapi_app_dir: Path):
        d = PythonDetector()
        result = d.detect(fastapi_app_dir)
        assert result is not None
        assert result["language"] == "python"
        assert result["framework"] == "fastapi"

    def test_detects_django(self, django_app_dir: Path):
        d = PythonDetector()
        result = d.detect(django_app_dir)
        assert result is not None
        assert result["language"] == "python"
        assert result["framework"] == "django"

    def test_infers_postgres(self, fastapi_app_dir: Path):
        d = PythonDetector()
        result = d.detect(fastapi_app_dir)
        assert "postgres" in result["dependencies"]["inferred_services"]

    def test_infers_celery_redis(self, django_app_dir: Path):
        d = PythonDetector()
        result = d.detect(django_app_dir)
        services = result["dependencies"]["inferred_services"]
        assert "redis" in services or "worker" in services

    def test_no_match_on_empty_dir(self, tmp_path: Path):
        d = PythonDetector()
        assert not d.matches(tmp_path)


# ---------------------------------------------------------------------------
# Node detector
# ---------------------------------------------------------------------------


class TestNodeDetector:
    def test_matches_package_json(self, express_app_dir: Path):
        d = NodeDetector()
        assert d.matches(express_app_dir)

    def test_detects_express(self, express_app_dir: Path):
        d = NodeDetector()
        result = d.detect(express_app_dir)
        assert result is not None
        assert result["language"] == "node"
        assert result["framework"] == "express"

    def test_infers_postgres_and_redis(self, express_app_dir: Path):
        d = NodeDetector()
        result = d.detect(express_app_dir)
        services = result["dependencies"]["inferred_services"]
        assert "postgres" in services
        assert "redis" in services

    def test_no_match_on_empty_dir(self, tmp_path: Path):
        d = NodeDetector()
        assert not d.matches(tmp_path)


# ---------------------------------------------------------------------------
# Go detector
# ---------------------------------------------------------------------------


class TestGoDetector:
    def test_matches_go_mod(self, go_app_dir: Path):
        d = GoDetector()
        assert d.matches(go_app_dir)

    def test_detects_gin(self, go_app_dir: Path):
        d = GoDetector()
        result = d.detect(go_app_dir)
        assert result is not None
        assert result["language"] == "go"
        assert result["framework"] == "gin"

    def test_infers_redis(self, go_app_dir: Path):
        d = GoDetector()
        result = d.detect(go_app_dir)
        services = result["dependencies"]["inferred_services"]
        assert "redis" in services

    def test_no_match_on_empty_dir(self, tmp_path: Path):
        d = GoDetector()
        assert not d.matches(tmp_path)


@pytest.mark.parametrize("marker", ["requirements.txt", "pyproject.toml", "package.json", "go.mod", "Dockerfile"])
def test_analyzer_ignores_external_symlinked_inputs(tmp_path, marker):
    from ai_infra.analyzer.core import analyze

    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    samples = {
        "requirements.txt": "flask\npsycopg2-binary\n",
        "pyproject.toml": '[project]\ndependencies = ["redis"]\n',
        "package.json": '{"dependencies": {"express": "1", "pg": "1"}}',
        "go.mod": "module example.test/external\ngo 1.23\nrequire github.com/lib/pq v1.0.0\n",
        "Dockerfile": "FROM python:3.11\nEXPOSE 9123\n",
    }
    source = outside / marker
    source.write_text(samples[marker])
    (repo / marker).symlink_to(source)
    analysis = analyze(repo)
    assert analysis["language"] is None
    assert analysis["dependencies"]["raw"] == []
    assert analysis["detected_port"] is None
    assert "dockerfile_info" not in analysis


@pytest.mark.parametrize("entry", ["../outside/server.js", "absolute", "src/server.js"])
def test_node_entrypoint_cannot_leave_repository(tmp_path, entry):
    import json

    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    source = outside / "server.js"
    source.write_text("app.listen(9123);")
    (repo / "src").symlink_to(outside, target_is_directory=True)
    main = str(source) if entry == "absolute" else entry
    (repo / "package.json").write_text(json.dumps({"main": main, "dependencies": {"express": "1"}}))
    result = NodeDetector().detect(repo)
    assert result["entrypoint"] is None
    assert result["detected_port"] is None


def test_python_and_go_entrypoints_ignore_external_links(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("fastapi\n")
    (repo / "go.mod").write_text("module example.test/app\ngo 1.23\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "main.py").write_text("PORT = 9123\n")
    (outside / "main.go").write_text('http.ListenAndServe(":9123", nil)')
    (repo / "main.py").symlink_to(outside / "main.py")
    (repo / "cmd").symlink_to(outside, target_is_directory=True)
    (repo / "main.go").symlink_to(outside / "main.go")
    for detector in (PythonDetector(), GoDetector()):
        result = detector.detect(repo)
        assert result["entrypoint"] is None
        assert result["detected_port"] is None


def test_safe_read_allows_contained_symlink_and_rejects_broken_or_cyclic_links(tmp_path):
    from ai_infra.analyzer.detectors.base import safe_read

    root = tmp_path / "repo"
    root.mkdir()
    source = root / "deps.txt"
    source.write_text("flask\n")
    link = root / "requirements.txt"
    link.symlink_to(source)
    assert safe_read(root, link) == "flask\n"
    broken = root / "broken"
    broken.symlink_to(root / "missing")
    assert safe_read(root, broken) is None
    cycle = root / "cycle"
    cycle.symlink_to(cycle)
    assert safe_read(root, cycle) is None
