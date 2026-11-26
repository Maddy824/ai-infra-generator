"""Tests for generated-file tracking and hand-edit protection."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_infra.generator.generator import Generator
from ai_infra.state.state_manager import StateManager


class TestStateManagerTracking:
    def test_state_directory_symlink_is_rejected(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (repo / ".ai-infra").symlink_to(outside, target_is_directory=True)
        with pytest.raises(ValueError, match="State path"):
            StateManager(repo).init_state_dir()
        assert list(outside.iterdir()) == []

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

    @pytest.mark.parametrize("with_state", [False, True])
    def test_untracked_existing_files_are_protected(self, tmp_path: Path, sample_model, with_state):
        state = StateManager(tmp_path)
        if with_state:
            state.init_state_dir()
        names = ["docker-compose.yml", "Dockerfile.web", ".env.example", ".dockerignore",
                 "k8s/web-deployment.yaml", ".github/workflows/deploy.yml"]
        for name in names:
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# pre-existing\n")

        gen = Generator(tmp_path)
        files = gen.generate(sample_model, target="all")

        for name in names:
            path = tmp_path / name
            assert path not in files
            assert path in gen.skipped
            assert path.read_text() == "# pre-existing\n"
            assert not state.is_tracked(name)

        files = gen.generate(sample_model, target="all", force=True)
        for name in names:
            if name == ".dockerignore":
                assert tmp_path / name in gen.skipped
                assert (tmp_path / name).read_text() == "# pre-existing\n"
                assert not state.is_tracked(name)
            else:
                assert tmp_path / name in files
                assert state.is_tracked(name)

    def test_identical_untracked_file_is_not_adopted(self, tmp_path, sample_model):
        gen = Generator(tmp_path)
        gen.generate(sample_model, target="compose")
        state = StateManager(tmp_path)
        state.write_atomic("state.json", '{"files": {}}')
        gen.generate(sample_model, target="compose")
        assert not state.is_tracked("docker-compose.yml")
        assert tmp_path / "docker-compose.yml" in gen.skipped

    def test_unchanged_generated_file_can_be_updated(self, tmp_path, sample_model):
        gen = Generator(tmp_path)
        gen.generate(sample_model, target="compose")
        model = sample_model.model_copy(update={"services": [
            sample_model.services[0].model_copy(update={"image": "python:3.12-slim"}),
            *sample_model.services[1:],
        ]})
        assert tmp_path / "Dockerfile.web" in gen.generate(model, target="compose")
        assert "python:3.12-slim" in (tmp_path / "Dockerfile.web").read_text()

    def test_dirty_marker_without_hash_does_not_establish_ownership(self, tmp_repo_with_state, sample_model):
        path = tmp_repo_with_state / "docker-compose.yml"
        path.write_text("# mine\n")
        StateManager(tmp_repo_with_state).mark_dirty(path.name)
        Generator(tmp_repo_with_state).generate(sample_model, target="compose")
        assert path.read_text() == "# mine\n"

    def test_line_ending_edits_are_preserved(self, tmp_path, sample_model):
        gen = Generator(tmp_path)
        gen.generate(sample_model, target="compose")
        path = tmp_path / "docker-compose.yml"
        edited = path.read_bytes().replace(b"\n", b"\r\n")
        path.write_bytes(edited)
        gen.generate(sample_model, target="compose")
        assert path in gen.skipped
        assert path.read_bytes() == edited

    def test_symlink_output_is_not_followed_even_with_force(self, tmp_path, sample_model):
        original = tmp_path / "original.yml"
        original.write_text("# original\n")
        link = tmp_path / "docker-compose.yml"
        link.symlink_to(original)
        gen = Generator(tmp_path)
        gen.generate(sample_model, target="compose", force=True)
        assert link in gen.skipped
        assert original.read_text() == "# original\n"
        assert link.is_symlink()

    def test_invalid_target_raises(self, tmp_path: Path, sample_model):
        with pytest.raises(ValueError, match="Invalid target"):
            Generator(tmp_path).generate(sample_model, target="nope")
