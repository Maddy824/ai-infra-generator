import shutil
import subprocess
import sys
from pathlib import Path


def test_bundled_example_matches_offline_generation():
    root = Path(__file__).resolve().parents[3]
    subprocess.run([sys.executable, str(root / "examples/regenerate.py"), "--check"], cwd=root, check=True)


def test_regenerate_replaces_obsolete_snapshot_files(tmp_path):
    root = Path(__file__).resolve().parents[3]
    examples = tmp_path / "examples"
    shutil.copytree(root / "examples", examples)
    script = examples / "regenerate.py"
    generated = examples / "flask-postgres/generated"
    obsolete = generated / "retired" / "obsolete.yaml"
    obsolete.parent.mkdir()
    obsolete.write_text("retired: true\n")
    command = [sys.executable, str(script)]
    assert subprocess.run([*command, "--check"], cwd=tmp_path).returncode != 0
    assert obsolete.exists()
    subprocess.run(command, cwd=tmp_path, check=True)
    assert not obsolete.parent.exists()
    subprocess.run([*command, "--check"], cwd=tmp_path, check=True)
