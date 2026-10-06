"""Tests for generated-file tracking and hand-edit protection."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_infra.generator.generator import Generator
from ai_infra.state.state_manager import StateManager


class TestStateManagerTracking:
    def test_mark_clean_tracks_repo_relative_file(self, tmp_repo_with_state: Path):
        (tmp_repo_with_state / "k8s").mkdir()
        (tmp_repo_with_state / "k8s" / "web.yaml").write_text("a: 1\n")

        state = StateManager(tmp_repo_with_state)
        state.mark_clean("k8s/web.yaml")

        entry = state.get_state()["files"]["k8s/web.yaml"]
        assert entry["dirty"] is False
        assert len(entry["hash"]) == 64
        assert not state.is_dirty("k8s/web.yaml")
        assert not state.was_modified("k8s/web.yaml")

    def test_edit_is_detected(self, tmp_repo_with_state: Path):
        path = tmp_repo_with_state / "Dockerfile.web"
        path.write_text("FROM python\n")
        state = StateManager(tmp_repo_with_state)
        state.mark_clean("Dockerfile.web")

        path.write_text("FROM python:3.12\n")

        assert state.is_dirty("Dockerfile.web")
        assert state.was_modified("Dockerfile.web")

    def test_untracked_file_is_not_modified(self, tmp_repo_with_state: Path):
        (tmp_repo_with_state / "notes.txt").write_text("hi")
        assert not StateManager(tmp_repo_with_state).was_modified("notes.txt")


class TestGeneratorTracking:
    def test_generate_records_files_in_state(self, tmp_repo_with_state: Path, sample_model):
        files = Generator(tmp_repo_with_state).generate(sample_model, target="compose")

        tracked = StateManager(tmp_repo_with_state).get_state()["files"]
        assert files
        for f in files:
            assert f.relative_to(tmp_repo_with_state).as_posix() in tracked

    def test_hand_edited_file_is_skipped(self, tmp_repo_with_state: Path, sample_model):
        Generator(tmp_repo_with_state).generate(sample_model, target="compose")
        compose = tmp_repo_with_state / "docker-compose.yml"
        compose.write_text("# my edits\n")

        gen = Generator(tmp_repo_with_state)
        files = gen.generate(sample_model, target="compose")

        assert compose not in files
        assert gen.skipped == [compose]
        assert compose.read_text() == "# my edits\n"

    def test_force_overwrites_hand_edited_file(self, tmp_repo_with_state: Path, sample_model):
        Generator(tmp_repo_with_state).generate(sample_model, target="compose")
        compose = tmp_repo_with_state / "docker-compose.yml"
        compose.write_text("# my edits\n")

        gen = Generator(tmp_repo_with_state)
        files = gen.generate(sample_model, target="compose", force=True)

        assert compose in files
        assert gen.skipped == []
        assert compose.read_text() != "# my edits\n"
        assert not StateManager(tmp_repo_with_state).was_modified("docker-compose.yml")

    def test_untracked_existing_file_is_overwritten(self, tmp_path: Path, sample_model):
        # Without state there is no record of a previous generation.
        compose = tmp_path / "docker-compose.yml"
        compose.write_text("# pre-existing\n")

        files = Generator(tmp_path).generate(sample_model, target="compose")

        assert compose in files

    def test_invalid_target_raises(self, tmp_path: Path, sample_model):
        with pytest.raises(ValueError, match="Invalid target"):
            Generator(tmp_path).generate(sample_model, target="nope")
