"""Tests for language/framework detectors."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_infra.analyzer.detectors.python import PythonDetector
from ai_infra.analyzer.detectors.node import NodeDetector
from ai_infra.analyzer.detectors.go import GoDetector


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
