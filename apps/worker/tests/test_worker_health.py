import json
import os
from pathlib import Path
import subprocess
import sys


WORKER_SOURCE = Path(__file__).resolve().parents[1] / "src"


def test_health_command_returns_stable_process_status() -> None:
    """Removing the one-shot health command or changing its payload must fail."""
    environment = os.environ | {"PYTHONPATH": str(WORKER_SOURCE)}
    result = subprocess.run(
        [sys.executable, "-m", "patent_evidence_worker.main", "health"],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"service": "worker", "status": "ok", "phase": "P0"}
