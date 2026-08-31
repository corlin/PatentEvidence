import json
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_LOCK = PROJECT_ROOT / "provenance" / "sources.lock.json"
SOURCE_LOCK_VERIFIER = PROJECT_ROOT / "scripts" / "verify-source-lock.py"
SCAFFOLD_VERIFIER = PROJECT_ROOT / "scripts" / "verify-scaffold.py"


def test_source_lock_verifier_accepts_the_committed_lock_and_rejects_duplicate_names(
    tmp_path: Path,
) -> None:
    """A duplicate source name must invalidate an otherwise well-formed lock."""
    valid = subprocess.run(
        [sys.executable, str(SOURCE_LOCK_VERIFIER), str(SOURCE_LOCK)],
        capture_output=True,
        check=False,
        text=True,
    )
    assert valid.returncode == 0, valid.stderr

    invalid_lock = json.loads(SOURCE_LOCK.read_text(encoding="utf-8"))
    invalid_lock["sources"][1]["name"] = invalid_lock["sources"][0]["name"]
    invalid_path = tmp_path / "invalid.lock.json"
    invalid_path.write_text(json.dumps(invalid_lock), encoding="utf-8")
    invalid = subprocess.run(
        [sys.executable, str(SOURCE_LOCK_VERIFIER), str(invalid_path)],
        capture_output=True,
        check=False,
        text=True,
    )
    assert invalid.returncode != 0
    assert "source names must be unique" in invalid.stderr


def test_scaffold_verifier_accepts_the_project_and_reports_tracked_dotenv(
    tmp_path: Path,
) -> None:
    """A tracked .env file must be reported even when a scaffold is incomplete."""
    valid = subprocess.run(
        [sys.executable, str(SCAFFOLD_VERIFIER), "--root", str(PROJECT_ROOT)],
        capture_output=True,
        check=False,
        text=True,
    )
    assert valid.returncode == 0, valid.stderr

    fake_root = tmp_path / "invalid-scaffold"
    fake_root.mkdir()
    subprocess.run(["git", "init", "--quiet", str(fake_root)], check=True)
    (fake_root / ".env").write_text("SECRET=not-for-commit\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(fake_root), "add", ".env"], check=True)
    invalid = subprocess.run(
        [sys.executable, str(SCAFFOLD_VERIFIER), "--root", str(fake_root)],
        capture_output=True,
        check=False,
        text=True,
    )
    assert invalid.returncode != 0
    assert "tracked secret/runtime path: .env" in invalid.stderr
