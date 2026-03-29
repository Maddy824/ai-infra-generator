"""State directory manager for .ai-infra/ lifecycle and atomic file I/O."""

from __future__ import annotations

import hashlib
import json
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from ai_infra.config.settings import settings

if TYPE_CHECKING:
    from ai_infra.models.infra_model import InfraModel

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_STATE_FILENAME = "state.json"
_ANALYZER_OUTPUT_FILENAME = "analyzer_output.json"
_INFRA_MODEL_FILENAME = "infra_model.v1.json"
_PLAN_FILENAME = "plan.md"
_HINTS_FILENAME = "hints.yaml"

_HINTS_STARTER = """\
# hints.yaml — optional human guidance for ai-infra
#
# Use this file to steer the analyzer & planner toward the infrastructure
# choices you prefer.  Uncomment and edit the examples below.
#
# cloud_provider: aws          # aws | gcp | azure
# container_runtime: docker    # docker | podman
# orchestrator: kubernetes     # kubernetes | ecs | nomad
# ci_cd: github_actions        # github_actions | gitlab_ci | circleci
# iac_tool: terraform          # terraform | pulumi | cdk
#
# ignore_paths:
#   - vendor/
#   - third_party/
#
# extra_notes: |
#   We need GPU nodes for the training service.
"""


def _sha256(content: str) -> str:
    """Return the hex SHA-256 digest of *content* (UTF-8 encoded)."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# StateManager
# ---------------------------------------------------------------------------


class StateManager:
    """Manages the ``.ai-infra/`` state directory.

    All writes go through a *write-to-temp-then-rename* pattern so that
    readers never see a partially-written file.
    """

    def __init__(self, repo_path: Path) -> None:
        self.repo_path = repo_path
        self.state_dir: Path = repo_path / settings.STATE_DIR_NAME

    # -- directory lifecycle ------------------------------------------------

    def init_state_dir(self) -> None:
        """Create ``.ai-infra/`` and its subdirectories (``logs/``)."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "logs").mkdir(exist_ok=True)

        # Bootstrap an empty state.json if it does not exist yet.
        state_path = self.state_dir / _STATE_FILENAME
        if not state_path.exists():
            self.write_atomic(_STATE_FILENAME, json.dumps({"files": {}}, indent=2))

    def exists(self) -> bool:
        """Return ``True`` if the state directory already exists."""
        return self.state_dir.is_dir()

    # -- generic I/O -------------------------------------------------------

    def write_atomic(self, filename: str, content: str) -> None:
        """Write *content* to ``state_dir/filename`` atomically.

        The data is first written to a temporary file in the same directory
        and then moved into place via :func:`os.replace`, guaranteeing that
        concurrent readers will never observe a partial write.
        """
        target = self.state_dir / filename
        target.parent.mkdir(parents=True, exist_ok=True)

        # Write to a temp file in the *same* directory so that os.replace is
        # guaranteed to be an atomic rename on the same filesystem.
        fd, tmp_path = tempfile.mkstemp(
            dir=str(target.parent),
            prefix=f".{target.name}.",
            suffix=".tmp",
        )
        try:
            with open(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
            Path(tmp_path).replace(target)
        except BaseException:
            # Clean up the temp file on any failure.
            Path(tmp_path).unlink(missing_ok=True)
            raise

    def read_file(self, filename: str) -> str:
        """Read and return the text content of ``state_dir/filename``."""
        target = self.state_dir / filename
        return target.read_text(encoding="utf-8")

    # -- analyzer output ----------------------------------------------------

    def write_analyzer_output(self, data: dict) -> None:
        """Serialize *data* as JSON and write ``analyzer_output.json`` atomically."""
        self.write_atomic(_ANALYZER_OUTPUT_FILENAME, json.dumps(data, indent=2))

    def read_analyzer_output(self) -> dict:
        """Read and return the parsed ``analyzer_output.json``."""
        raw = self.read_file(_ANALYZER_OUTPUT_FILENAME)
        return json.loads(raw)

    # -- infra model --------------------------------------------------------

    def write_infra_model(self, model: InfraModel) -> None:
        """Serialize a Pydantic *model* and write ``infra_model.v1.json`` atomically."""
        self.write_atomic(
            _INFRA_MODEL_FILENAME,
            json.dumps(model.model_dump(), indent=2),
        )

    def read_infra_model(self) -> InfraModel:
        """Read ``infra_model.v1.json`` and return a validated :class:`InfraModel`."""
        from ai_infra.models.infra_model import InfraModel

        raw = self.read_file(_INFRA_MODEL_FILENAME)
        return InfraModel.model_validate(json.loads(raw))

    # -- plan ---------------------------------------------------------------

    def write_plan_summary(self, content: str) -> None:
        """Write ``plan.md`` atomically."""
        self.write_atomic(_PLAN_FILENAME, content)

    # -- hints --------------------------------------------------------------

    def read_hints(self) -> dict:
        """Read ``hints.yaml`` and return its contents.

        Returns an empty ``dict`` when the file does not exist or is empty.
        """
        try:
            raw = self.read_file(_HINTS_FILENAME)
        except FileNotFoundError:
            return {}

        parsed = yaml.safe_load(raw)
        return parsed if isinstance(parsed, dict) else {}

    def write_hints_starter(self) -> None:
        """Write a starter ``hints.yaml`` with commented-out examples."""
        self.write_atomic(_HINTS_FILENAME, _HINTS_STARTER)

    # -- dirty / clean tracking --------------------------------------------

    def get_state(self) -> dict:
        """Read and return the parsed ``state.json``."""
        try:
            raw = self.read_file(_STATE_FILENAME)
            return json.loads(raw)
        except FileNotFoundError:
            return {"files": {}}

    def _save_state(self, state: dict) -> None:
        """Persist *state* to ``state.json`` atomically."""
        self.write_atomic(_STATE_FILENAME, json.dumps(state, indent=2))

    def mark_dirty(self, filename: str) -> None:
        """Mark *filename* as dirty in ``state.json``."""
        state = self.get_state()
        files = state.setdefault("files", {})
        files.setdefault(filename, {})
        files[filename]["dirty"] = True
        self._save_state(state)

    def mark_clean(self, filename: str) -> None:
        """Mark *filename* as clean in ``state.json``."""
        state = self.get_state()
        files = state.setdefault("files", {})

        # Compute the hash of the file's current contents.
        target = self.state_dir / filename
        content = target.read_text(encoding="utf-8")
        content_hash = _sha256(content)

        files[filename] = {
            "dirty": False,
            "hash": content_hash,
            "generated_at": time.time(),
        }
        self._save_state(state)

    def is_dirty(self, filename: str) -> bool:
        """Return ``True`` if *filename* needs to be regenerated."""
        state = self.get_state()
        files = state.get("files", {})

        if filename not in files:
            return True

        entry = files[filename]

        if entry.get("dirty", True):
            return True

        # Compare the stored hash against the current file on disk.
        target = self.state_dir / filename
        if not target.exists():
            return True

        current_hash = _sha256(target.read_text(encoding="utf-8"))
        return current_hash != entry.get("hash")
