from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
from threading import Event
from typing import Sequence

def health_payload() -> dict[str, str]:
    return {"service": "worker", "status": "ok", "phase": "P0"}


async def _worker_loop(stop_event: Event) -> None:
    worker_db_url = (
        os.environ.get("PATENT_EVIDENCE_WORKER_DATABASE_URL")
        or os.environ.get("PE_WORKER_DATABASE_URL")
        or os.environ.get("PE_TEST_WORKER_DATABASE_URL")
    )
    if not worker_db_url:
        # If no DB URL configured, fall back to waiting for stop event
        while not stop_event.is_set():
            await asyncio.sleep(0.5)
        return

    from adapters.object_storage.client import ObjectStorageClient
    from patent_evidence_api.core.database import create_engine, create_worker_session_factory
    from patent_evidence_worker.parse_worker import ParseTaskWorker

    worker_engine = create_engine(worker_db_url)
    worker_session_factory = create_worker_session_factory(worker_engine)
    storage = ObjectStorageClient()
    worker = ParseTaskWorker(worker_session_factory, storage)

    try:
        while not stop_event.is_set():
            try:
                did_work = await worker.run_once()
                if not did_work:
                    await asyncio.sleep(1.0)
            except Exception:
                await asyncio.sleep(2.0)
    finally:
        await worker_engine.dispose()


def run_service(stop_event: Event | None = None) -> None:
    """Run worker daemon processing loop with graceful shutdown."""
    stop = stop_event or Event()

    def request_stop(_signal_number: int, _frame: object) -> None:
        stop.set()

    try:
        signal.signal(signal.SIGINT, request_stop)
        signal.signal(signal.SIGTERM, request_stop)
    except (ValueError, AttributeError):
        pass  # In some thread contexts signal setting is ignored

    asyncio.run(_worker_loop(stop))


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
