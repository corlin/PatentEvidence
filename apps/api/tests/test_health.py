import json
import os
from pathlib import Path
import subprocess
import sys


API_SOURCE = Path(__file__).resolve().parents[1] / "src"


def test_health_endpoint_returns_stable_process_status() -> None:
    """Removing the app route or changing its process-health payload must fail."""
    command = """
import json
from fastapi.testclient import TestClient
from patent_evidence_api.main import app

response = TestClient(app).get('/health')
print(json.dumps({'status_code': response.status_code, 'body': response.json()}))
"""
    environment = os.environ | {"PYTHONPATH": str(API_SOURCE)}
    result = subprocess.run(
        [sys.executable, "-c", command],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "status_code": 200,
        "body": {"service": "api", "status": "ok", "phase": "P0"},
    }
