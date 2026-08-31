import json
from pathlib import Path
import subprocess
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_LOCK = PROJECT_ROOT / "provenance" / "sources.lock.json"
SOURCE_LOCK_VERIFIER = PROJECT_ROOT / "scripts" / "verify-source-lock.py"
SCAFFOLD_VERIFIER = PROJECT_ROOT / "scripts" / "verify-scaffold.py"


def run_source_lock_verifier(lock_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SOURCE_LOCK_VERIFIER), str(lock_path)],
        capture_output=True,
        check=False,
        text=True,
    )


def write_lock(tmp_path: Path, payload: dict[str, object]) -> Path:
    lock_path = tmp_path / "invalid.lock.json"
    lock_path.write_text(json.dumps(payload), encoding="utf-8")
    return lock_path


def test_source_lock_verifier_accepts_the_committed_lock_and_rejects_duplicate_names(
    tmp_path: Path,
) -> None:
    """A duplicate source name must invalidate an otherwise well-formed lock."""
    valid = run_source_lock_verifier(SOURCE_LOCK)
    assert valid.returncode == 0, valid.stderr

    invalid_lock = json.loads(SOURCE_LOCK.read_text(encoding="utf-8"))
    invalid_lock["sources"][1]["name"] = invalid_lock["sources"][0]["name"]
    invalid = run_source_lock_verifier(write_lock(tmp_path, invalid_lock))
    assert invalid.returncode != 0
    assert "source names must be unique" in invalid.stderr


def test_source_lock_verifier_rejects_an_unauthorized_valid_format_commit(tmp_path: Path) -> None:
    """The PatentQ record must retain its approved full commit, not just hash shape."""
    invalid_lock = json.loads(SOURCE_LOCK.read_text(encoding="utf-8"))
    invalid_lock["sources"][0]["commit"] = "f" * 40

    invalid = run_source_lock_verifier(write_lock(tmp_path, invalid_lock))

    assert invalid.returncode != 0
    assert "source 1 commit does not match approved source lock" in invalid.stderr


def test_source_lock_verifier_rejects_an_unauthorized_repository(tmp_path: Path) -> None:
    """The PatentQ record must retain its approved repository URL."""
    invalid_lock = json.loads(SOURCE_LOCK.read_text(encoding="utf-8"))
    invalid_lock["sources"][0]["repository"] = "https://github.com/example/PatentQ.git"

    invalid = run_source_lock_verifier(write_lock(tmp_path, invalid_lock))

    assert invalid.returncode != 0
    assert "source 1 repository does not match approved source lock" in invalid.stderr


@pytest.mark.parametrize(
    ("field", "value", "expected_error"),
    [
        ("license_status", "", "source 1 license_status must be a non-empty string"),
        ("integration", "", "source 1 integration must be a non-empty string"),
        ("scope", [], "source 1 scope must be a non-empty list of non-empty strings"),
    ],
)
def test_source_lock_verifier_requires_provenance_metadata(
    tmp_path: Path,
    field: str,
    value: object,
    expected_error: str,
) -> None:
    """Each approved source needs the provenance metadata consumed by governance."""
    invalid_lock = json.loads(SOURCE_LOCK.read_text(encoding="utf-8"))
    invalid_lock["sources"][0][field] = value

    invalid = run_source_lock_verifier(write_lock(tmp_path, invalid_lock))

    assert invalid.returncode != 0
    assert expected_error in invalid.stderr


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
