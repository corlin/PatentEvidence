import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[3]


def _run(script: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def test_bootstrap_cli_never_accepts_password_positionally() -> None:
    help_result = _run("bootstrap-platform-admin.py", "--help")
    assert help_result.returncode == 0
    assert "--password" not in help_result.stdout
    rejected = _run(
        "bootstrap-platform-admin.py",
        "admin@example.test",
        "Admin",
        "secret-on-command-line",
    )
    assert rejected.returncode != 0
    assert "secret-on-command-line" not in rejected.stdout + rejected.stderr


def test_create_organization_cli_is_an_http_client() -> None:
    help_result = _run("create-organization.py", "--help")
    assert help_result.returncode == 0
    assert "--api-url" in help_result.stdout
    assert "--idempotency-key" in help_result.stdout
    source = (ROOT / "scripts" / "create-organization.py").read_text()
    assert "httpx" in source
    assert "sqlalchemy" not in source
    assert "psycopg" not in source
