import argparse
import json
import signal
from threading import Event
from typing import Sequence


def health_payload() -> dict[str, str]:
    return {"service": "worker", "status": "ok", "phase": "P0"}


def run_service(stop_event: Event | None = None) -> None:
    """Keep the worker process alive without a busy loop until it is stopped."""
    stop = stop_event or Event()

    def request_stop(_signal_number: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    stop.wait()


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PatentEvidence worker")
    parser.add_argument("command", choices=("health", "service"))
    parsed = parser.parse_args(arguments)

    if parsed.command == "health":
        print(json.dumps(health_payload(), separators=(",", ":")))
        return 0

    run_service()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
