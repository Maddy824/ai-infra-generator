"""Regenerate the example snapshot using the installed offline CLI."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

EXAMPLE = Path(__file__).resolve().parent / "flask-postgres"


def snapshot(directory: Path) -> dict[str, bytes]:
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify the snapshot without changing it.")
    args = parser.parse_args()
    with TemporaryDirectory(prefix="example-", dir=EXAMPLE.parent) as temp:
        repo = Path(temp) / EXAMPLE.name
        repo.mkdir()
        for name in ("app.py", "requirements.txt"):
            shutil.copyfile(EXAMPLE / name, repo / name)
        subprocess.run([sys.executable, "-m", "ai_infra", "run", str(repo), "--offline"], check=True)

        # Only capture generated infrastructure, not source or timestamped state.
        from ai_infra.state.state_manager import StateManager

        files = StateManager(repo).get_state()["files"]
        actual = {name: (repo / name).read_bytes() for name in files}
        destination = EXAMPLE / "generated"
        if args.check:
            if actual != snapshot(destination):
                sys.exit("Example output differs. Run python examples/regenerate.py and review the changes.")
            print("Example snapshot matches.")
        else:
            replacement = Path(temp) / "generated"
            replacement.mkdir()
            for name, contents in actual.items():
                path = replacement / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(contents)
            if destination.exists():
                shutil.rmtree(destination)
            replacement.rename(destination)
            print(f"Wrote {len(actual)} files to {destination}")


if __name__ == "__main__":
    main()
