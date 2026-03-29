"""Fix Loop -- parse deployment logs, classify errors, and propose targeted patches.

Three-layer pipeline:
1. **Log parser** — maps raw logs to structured ``InfraError`` instances.
2. **Planner (repair mode)** — receives structured errors, proposes targeted
   patches to the Infra Model (not full regeneration).
3. **Targeted re-render** — only files affected by patched services are
   regenerated.

Supports ``--dry-run`` to preview changes without writing files.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from ai_infra.config.settings import settings
from ai_infra.generator.generator import Generator
from ai_infra.models.infra_model import InfraModel
from ai_infra.planner.prompts import SYSTEM_PROMPT
from ai_infra.state.state_manager import StateManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Structured error schema
# ---------------------------------------------------------------------------

ErrorKind = Literal["build", "runtime", "oom", "crashloop", "image_pull"]


@dataclass(frozen=True)
class InfraError:
    """A single classified infrastructure error extracted from logs."""

    kind: ErrorKind
    component: str  # service name
    evidence: str  # relevant log snippet


# ---------------------------------------------------------------------------
# Log parsing patterns
# ---------------------------------------------------------------------------

_ERROR_PATTERNS: list[tuple[re.Pattern[str], ErrorKind, int | None]] = [
    # OOM killed
    (re.compile(r"(?:OOMKilled|Out of memory|oom-kill|memory cgroup out of memory)", re.IGNORECASE), "oom", None),
    # CrashLoopBackOff
    (re.compile(r"CrashLoopBackOff", re.IGNORECASE), "crashloop", None),
    # Image pull errors
    (re.compile(r"(?:ImagePullBackOff|ErrImagePull|image.*not found|pull access denied)", re.IGNORECASE), "image_pull", None),
    # Build errors
    (re.compile(r"(?:COPY failed|RUN.*returned a non-zero|error building|build.*failed|no such file or directory)", re.IGNORECASE), "build", None),
    # Generic runtime errors (catch-all, lower priority)
    (re.compile(r"(?:Error|FATAL|panic|Traceback|exception|segfault)", re.IGNORECASE), "runtime", None),
]

# Patterns to extract a service/container name from a log line
_COMPONENT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"container[= ]+[\"']?(\w[\w-]*)"),
    re.compile(r"pod[/ ]+[\"']?(\w[\w-]*)"),
    re.compile(r"service[/ ]+[\"']?(\w[\w-]*)"),
    re.compile(r"Building (\w[\w-]*)"),
    re.compile(r"Step \d+/\d+ : FROM .+?AS (\w+)"),
    re.compile(r"\[(\w[\w-]*)\]\s"),
]

_CONTEXT_LINES = 3  # lines of surrounding context to capture as evidence


def _extract_component(line: str, all_service_names: list[str]) -> str:
    """Try to identify the service/component name from a log line."""
    # Priority 1: check if any known service name appears in the line
    line_lower = line.lower()
    for svc in all_service_names:
        if svc in line_lower:
            return svc

    # Priority 2: try explicit regex patterns
    for pat in _COMPONENT_PATTERNS:
        m = pat.search(line)
        if m:
            candidate = m.group(1).lower().strip("-_")
            if candidate:
                return candidate

    return "unknown"


def parse_logs(log_content: str, service_names: list[str] | None = None) -> list[InfraError]:
    """Parse raw log text and return a list of structured errors."""
    names = service_names or []
    lines = log_content.splitlines()
    errors: list[InfraError] = []
    seen: set[tuple[str, str]] = set()  # (kind, component) dedup

    for idx, line in enumerate(lines):
        for pattern, kind, _ in _ERROR_PATTERNS:
            if pattern.search(line):
                component = _extract_component(line, names)
                key = (kind, component)
                if key in seen:
                    break
                seen.add(key)

                # Capture surrounding context as evidence
                start = max(0, idx - _CONTEXT_LINES)
                end = min(len(lines), idx + _CONTEXT_LINES + 1)
                evidence = "\n".join(lines[start:end])

                errors.append(InfraError(
                    kind=kind,
                    component=component,
                    evidence=evidence,
                ))
                break  # first matching pattern wins for this line

    return errors


# ---------------------------------------------------------------------------
# Patch proposal via Planner (repair mode)
# ---------------------------------------------------------------------------

_FIX_PROMPT = """A deployment ran into some issues. Here's the current infrastructure model and the \
errors that were detected. The goal is to make targeted adjustments so the next deploy succeeds.

## Current Infra Model
{infra_model}

## Errors Detected
{errors}

## How to think about fixes

- **OOM errors** usually mean a service needs more breathing room — bumping memory_limits by 50–100% \
for the affected service tends to resolve it.
- **CrashLoop errors** are often a startup ordering issue — check whether depends_on is missing a \
database or cache that the service needs before it can start.
- **Build errors** typically point to something in the Dockerfile setup — the base image, entrypoint, \
or a file path that doesn't match the project layout.
- **Image pull errors** mean the image reference can't be found — usually a typo or a private registry \
without credentials. Switching to a known-good public image often helps.
- **Runtime errors** can come from many places, but misconfigured environment variables or wrong port \
mappings are common culprits.

The key is to be surgical — adjust only what's needed for the affected service rather than \
reworking the whole model. Keep the version, project_name, and overall structure intact.

Please provide the fixed InfraModel as JSON.
"""


def _propose_patches_via_llm(
    model: InfraModel,
    errors: list[InfraError],
) -> InfraModel:
    """Call the LLM to propose a patched InfraModel based on detected errors."""
    from ai_infra.planner.planner import Planner

    errors_text = json.dumps([asdict(e) for e in errors], indent=2)
    model_text = model.model_dump_json(indent=2)

    prompt = _FIX_PROMPT.format(
        infra_model=model_text,
        errors=errors_text,
    )

    # Re-use the planner's LLM call machinery with retry
    planner = Planner.__new__(Planner)
    planner.repo_path = Path(".")
    planner.state = None  # not needed for LLM calls

    last_error: ValidationError | None = None

    for attempt in range(settings.LLM_MAX_RETRIES + 1):
        if attempt == 0:
            raw = planner._call_llm(SYSTEM_PROMPT, prompt)
        else:
            from ai_infra.planner.prompts import REPAIR_PROMPT
            repair = REPAIR_PROMPT.format(
                validation_error=str(last_error),
                original_prompt=prompt,
            )
            raw = planner._call_llm(SYSTEM_PROMPT, repair)

        try:
            cleaned = planner._clean_json(raw)
            patched = InfraModel.model_validate_json(cleaned)
            return patched
        except ValidationError as exc:
            last_error = exc

    raise RuntimeError(
        f"Fix loop LLM failed after {settings.LLM_MAX_RETRIES + 1} attempts. "
        f"Last error: {last_error}"
    )


def _propose_patches_deterministic(
    model: InfraModel,
    errors: list[InfraError],
) -> InfraModel:
    """Apply deterministic patches without LLM for common error patterns."""
    data = model.model_dump()

    for error in errors:
        svc_idx = _find_service_index(data, error.component)
        if svc_idx is None:
            logger.warning("Cannot find service '%s' in model; skipping.", error.component)
            continue

        svc = data["services"][svc_idx]

        if error.kind == "oom":
            # Double the memory limits
            old_limit = svc["sizing"]["memory_limits"]
            new_limit = _scale_memory(old_limit, 2.0)
            svc["sizing"]["memory_limits"] = new_limit
            logger.info("OOM fix: %s memory_limits %s -> %s", error.component, old_limit, new_limit)

        elif error.kind == "crashloop":
            _fix_depends_on(data, svc_idx)
            logger.info("CrashLoop fix: updated depends_on for %s", error.component)

        elif error.kind == "image_pull":
            logger.warning(
                "image_pull error for %s -- cannot fix deterministically. "
                "Consider running with LLM backend.",
                error.component,
            )

        elif error.kind == "build":
            logger.warning(
                "build error for %s -- cannot fix deterministically. "
                "Consider running with LLM backend.",
                error.component,
            )

        elif error.kind == "runtime":
            logger.warning(
                "runtime error for %s -- cannot fix deterministically. "
                "Consider running with LLM backend.",
                error.component,
            )

    return InfraModel.model_validate(data)


def _find_service_index(data: dict, component: str) -> int | None:
    """Find the index of a service by name in the model dict."""
    for i, svc in enumerate(data.get("services", [])):
        if svc["name"] == component:
            return i
    return None


_MEM_PATTERN = re.compile(r"^(\d+)(Mi|Gi|Ki)$")


def _scale_memory(value: str, factor: float) -> str:
    """Scale a Kubernetes memory string by *factor*."""
    m = _MEM_PATTERN.match(value)
    if not m:
        return value  # cannot parse, return as-is
    num = int(m.group(1))
    unit = m.group(2)
    new_num = int(num * factor)
    return f"{new_num}{unit}"


def _fix_depends_on(data: dict, svc_idx: int) -> None:
    """Ensure that app/worker services depend on their database/cache services."""
    svc = data["services"][svc_idx]
    svc_type = svc.get("type", "app")

    if svc_type not in ("app", "worker"):
        return

    existing_deps = set(svc.get("depends_on", []))
    infra_services = []
    for other in data["services"]:
        if other["name"] == svc["name"]:
            continue
        if other.get("type") in ("database", "cache"):
            infra_services.append(other["name"])

    for dep in infra_services:
        if dep not in existing_deps:
            svc.setdefault("depends_on", []).append(dep)
            logger.info("Added depends_on %s -> %s", svc["name"], dep)


# ---------------------------------------------------------------------------
# Diff generation for dry-run
# ---------------------------------------------------------------------------


def _compute_diff(old_model: InfraModel, new_model: InfraModel) -> list[str]:
    """Compute human-readable changes between two InfraModel instances."""
    changes: list[str] = []
    old = old_model.model_dump()
    new = new_model.model_dump()

    for i, (old_svc, new_svc) in enumerate(
        zip(old.get("services", []), new.get("services", []))
    ):
        name = old_svc.get("name", f"service[{i}]")
        _diff_dict(changes, name, old_svc, new_svc, prefix="")

    # Check for added/removed services
    old_names = {s["name"] for s in old.get("services", [])}
    new_names = {s["name"] for s in new.get("services", [])}
    for added in new_names - old_names:
        changes.append(f"+ Added service: {added}")
    for removed in old_names - new_names:
        changes.append(f"- Removed service: {removed}")

    return changes


def _diff_dict(changes: list[str], svc_name: str, old: dict, new: dict, prefix: str) -> None:
    """Recursively diff two dicts and append human-readable changes."""
    all_keys = set(old.keys()) | set(new.keys())
    for key in sorted(all_keys):
        old_val = old.get(key)
        new_val = new.get(key)
        path = f"{prefix}.{key}" if prefix else key

        if old_val == new_val:
            continue

        if isinstance(old_val, dict) and isinstance(new_val, dict):
            _diff_dict(changes, svc_name, old_val, new_val, path)
        else:
            changes.append(f"[{svc_name}] {path}: {old_val!r} -> {new_val!r}")


# ---------------------------------------------------------------------------
# FixLoop orchestrator
# ---------------------------------------------------------------------------


class FixLoop:
    """Parse deployment logs, classify errors, and propose/apply fixes."""

    def __init__(self, repo_path: Path) -> None:
        self.repo_path = repo_path
        self.state = StateManager(repo_path)

    def fix(self, log_path: Path, *, dry_run: bool = False) -> dict:
        """Run the full fix loop."""
        # 1. Read the current infra model
        try:
            model = self.state.read_infra_model()
        except FileNotFoundError:
            raise RuntimeError(
                "No infra model found. Run 'ai-infra plan' before using fix."
            )

        service_names = [s.name for s in model.services]

        # 2. Parse logs into structured errors
        log_content = log_path.read_text(encoding="utf-8", errors="replace")
        errors = parse_logs(log_content, service_names)

        if not errors:
            logger.info("No errors detected in logs.")
            return {"errors": [], "changes": [], "files": []}

        logger.info("Detected %d error(s): %s", len(errors), [(e.kind, e.component) for e in errors])

        # Write parsed errors to logs/ for audit trail
        self.state.init_state_dir()
        errors_json = json.dumps([asdict(e) for e in errors], indent=2)
        self.state.write_atomic("logs/fix_errors.json", errors_json)

        # 3. Propose patches
        needs_llm = any(e.kind in ("image_pull", "build") for e in errors)
        if needs_llm:
            try:
                patched_model = _propose_patches_via_llm(model, errors)
            except RuntimeError:
                logger.warning("LLM fix failed; falling back to deterministic patches.")
                patched_model = _propose_patches_deterministic(model, errors)
        else:
            patched_model = _propose_patches_deterministic(model, errors)

        # 4. Compute diff
        changes = _compute_diff(model, patched_model)

        if not changes:
            logger.info("No changes proposed by the fix loop.")
            return {
                "errors": [asdict(e) for e in errors],
                "changes": [],
                "files": [],
            }

        # 5. Apply or preview
        written_files: list[str] = []
        if dry_run:
            logger.info("Dry run -- changes would be:")
            for c in changes:
                logger.info("  %s", c)
        else:
            # Write the patched model
            self.state.write_infra_model(patched_model)

            # Determine affected services and regenerate only those files
            affected = _affected_services(model, patched_model)
            if affected:
                gen = Generator(self.repo_path)
                files = gen.generate(patched_model, target="all", force=True)
                written_files = [str(f) for f in files]
            else:
                written_files = []

            # Log the fix
            fix_log = {
                "errors": [asdict(e) for e in errors],
                "changes": changes,
                "files_written": written_files,
            }
            self.state.write_atomic(
                "logs/fix_result.json",
                json.dumps(fix_log, indent=2),
            )

        return {
            "errors": [asdict(e) for e in errors],
            "changes": changes,
            "files": written_files,
        }


def _affected_services(old: InfraModel, new: InfraModel) -> set[str]:
    """Return names of services that changed between two models."""
    old_map = {s.name: s.model_dump() for s in old.services}
    new_map = {s.name: s.model_dump() for s in new.services}

    changed: set[str] = set()
    all_names = set(old_map.keys()) | set(new_map.keys())

    for name in all_names:
        if old_map.get(name) != new_map.get(name):
            changed.add(name)

    return changed
