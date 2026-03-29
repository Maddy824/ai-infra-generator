"""Tests for the Planner module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_infra.models.infra_model import InfraModel
from ai_infra.planner.planner import Planner
from ai_infra.state.state_manager import StateManager


# ---------------------------------------------------------------------------
# JSON cleaning
# ---------------------------------------------------------------------------


class TestCleanJson:
    def test_strips_json_fence(self):
        raw = '```json\n{"project_name": "x"}\n```'
        assert Planner._clean_json(raw) == '{"project_name": "x"}'

    def test_strips_plain_fence(self):
        raw = '```\n{"project_name": "x"}\n```'
        assert Planner._clean_json(raw) == '{"project_name": "x"}'

    def test_strips_whitespace(self):
        raw = '  \n{"project_name": "x"}\n  '
        assert Planner._clean_json(raw) == '{"project_name": "x"}'

    def test_no_fences(self):
        raw = '{"project_name": "x"}'
        assert Planner._clean_json(raw) == '{"project_name": "x"}'


# ---------------------------------------------------------------------------
# Plan summary
# ---------------------------------------------------------------------------


class TestPlanSummary:
    def test_summary_contains_project_name(self, sample_model):
        summary = Planner._format_summary(sample_model)
        assert "test-project" in summary

    def test_summary_contains_service_names(self, sample_model):
        summary = Planner._format_summary(sample_model)
        assert "web" in summary
        assert "postgres" in summary
        assert "redis" in summary

    def test_summary_contains_scale(self, sample_model):
        summary = Planner._format_summary(sample_model)
        assert "dev" in summary

    def test_summary_contains_env_info(self, sample_model):
        summary = Planner._format_summary(sample_model)
        assert "DATABASE_URL" in summary


# ---------------------------------------------------------------------------
# Planner with mock LLM
# ---------------------------------------------------------------------------


class TestPlannerWithMockLLM:
    def test_plan_writes_model(
        self, tmp_repo_with_state, sample_analyzer_output, mock_llm_response
    ):
        state = StateManager(tmp_repo_with_state)
        state.write_analyzer_output(sample_analyzer_output)

        planner = Planner(tmp_repo_with_state)
        model = planner.plan(sample_analyzer_output)

        assert isinstance(model, InfraModel)
        assert model.project_name == "test-project"

        # Verify it was persisted
        loaded = state.read_infra_model()
        assert loaded.model_dump() == model.model_dump()

    def test_plan_writes_summary(
        self, tmp_repo_with_state, sample_analyzer_output, mock_llm_response
    ):
        state = StateManager(tmp_repo_with_state)
        state.write_analyzer_output(sample_analyzer_output)

        planner = Planner(tmp_repo_with_state)
        planner.plan(sample_analyzer_output)

        summary_path = tmp_repo_with_state / ".ai-infra" / "plan.md"
        assert summary_path.exists()
        summary = summary_path.read_text()
        assert "test-project" in summary

    def test_plan_reads_hints(
        self, tmp_repo_with_state, sample_analyzer_output, mock_llm_response
    ):
        state = StateManager(tmp_repo_with_state)
        state.write_analyzer_output(sample_analyzer_output)
        state.write_atomic("hints.yaml", "scale: prod\n")

        planner = Planner(tmp_repo_with_state)
        # Should not raise — hints are read and passed to the prompt
        model = planner.plan(sample_analyzer_output)
        assert isinstance(model, InfraModel)


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------


class TestPlannerRetry:
    def test_retries_on_invalid_json(
        self, tmp_repo_with_state, sample_analyzer_output, sample_model, monkeypatch
    ):
        """First attempt returns garbage, second returns valid JSON."""
        model_json = sample_model.model_dump_json(indent=2)
        call_count = {"n": 0}

        def _fake(self, system: str, user: str) -> str:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return '{"invalid": true}'
            return model_json

        monkeypatch.setattr("ai_infra.planner.planner.Planner._call_llm", _fake)

        state = StateManager(tmp_repo_with_state)
        state.write_analyzer_output(sample_analyzer_output)

        planner = Planner(tmp_repo_with_state)
        model = planner.plan(sample_analyzer_output)
        assert isinstance(model, InfraModel)
        assert call_count["n"] >= 2

    def test_fails_after_max_retries(
        self, tmp_repo_with_state, sample_analyzer_output, monkeypatch
    ):
        """All attempts return garbage → RuntimeError."""

        def _always_bad(self, system: str, user: str) -> str:
            return '{"completely": "invalid"}'

        monkeypatch.setattr("ai_infra.planner.planner.Planner._call_llm", _always_bad)

        state = StateManager(tmp_repo_with_state)
        state.write_analyzer_output(sample_analyzer_output)

        planner = Planner(tmp_repo_with_state)
        with pytest.raises(RuntimeError, match="failed after"):
            planner.plan(sample_analyzer_output)
