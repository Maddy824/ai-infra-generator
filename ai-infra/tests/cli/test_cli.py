"""Tests for the Typer CLI."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from ai_infra.generator.generator import Generator
from ai_infra.state.state_manager import StateManager
from cli.main import app

runner = CliRunner()


def test_missing_repo_dir_fails(tmp_path: Path):
    result = runner.invoke(app, ["analyze", str(tmp_path / "nope")])
    assert result.exit_code != 0


def test_run_rejects_bad_target_before_planning(tmp_path: Path, monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("planner should not be called")

    monkeypatch.setattr("ai_infra.planner.planner.Planner.plan", _boom)
    result = runner.invoke(app, ["run", str(tmp_path), "--target", "nope"])
    assert result.exit_code == 1
    assert "Invalid target" in result.output


def test_generate_reports_skipped_hand_edits(tmp_repo_with_state: Path, sample_model):
    StateManager(tmp_repo_with_state).write_infra_model(sample_model)
    Generator(tmp_repo_with_state).generate(sample_model, target="compose")
    (tmp_repo_with_state / "docker-compose.yml").write_text("# mine\n")

    result = runner.invoke(app, ["generate", str(tmp_repo_with_state), "--target", "compose"])

    assert result.exit_code == 0
    assert "Skipped 1 hand-edited file" in result.output
    assert "docker-compose.yml" in result.output


def test_status_lists_modified_files(tmp_repo_with_state: Path, sample_model):
    StateManager(tmp_repo_with_state).write_infra_model(sample_model)
    Generator(tmp_repo_with_state).generate(sample_model, target="compose")
    (tmp_repo_with_state / "docker-compose.yml").write_text("# mine\n")

    result = runner.invoke(app, ["status", str(tmp_repo_with_state)])

    assert result.exit_code == 0
    assert "Modified since generation (1)" in result.output
