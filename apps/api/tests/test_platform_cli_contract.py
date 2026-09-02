import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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


def test_create_organization_cli_sends_the_documented_http_contract() -> None:
    captured: dict[str, object] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers["Content-Length"])
            captured.update(
                path=self.path,
                body=json.loads(self.rfile.read(length)),
                cookie=self.headers.get("Cookie"),
                idempotency_key=self.headers.get("Idempotency-Key"),
            )
            response = json.dumps({"organization": {"id": "organization-1"}}).encode()
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "create-organization.py"),
                "--api-url",
                f"http://127.0.0.1:{server.server_port}",
                "--idempotency-key",
                "cli-open-1",
                "--slug",
                "cli-org",
                "--display-name",
                "CLI Organization",
                "--admin-email",
                "admin@cli.test",
                "--plan-key",
                "manual",
                "--monthly-case-allowance",
                "5",
                "--current-period-start",
                "2026-09-01T00:00:00+00:00",
                "--current-period-end",
                "2026-10-01T00:00:00+00:00",
            ],
            check=False,
            capture_output=True,
            text=True,
            env={**os.environ, "PATENT_EVIDENCE_SESSION_TOKEN": "cli-session"},
        )
    finally:
        server.shutdown()
        thread.join()
        server.server_close()

    assert result.returncode == 0
    assert captured == {
        "path": "/api/v1/platform/organizations",
        "body": {
            "slug": "cli-org",
            "display_name": "CLI Organization",
            "admin_email": "admin@cli.test",
            "plan_key": "manual",
            "monthly_case_allowance": 5,
            "current_period_start": "2026-09-01T00:00:00+00:00",
            "current_period_end": "2026-10-01T00:00:00+00:00",
            "expires_at": None,
        },
        "cookie": "pe_session=cli-session",
        "idempotency_key": "cli-open-1",
    }
