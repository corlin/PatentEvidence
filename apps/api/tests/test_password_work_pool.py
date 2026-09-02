import asyncio
from collections.abc import Callable
from contextlib import suppress
import threading

import pytest

from patent_evidence_api.auth.security import (
    BoundedPasswordWorkPool,
    PasswordWorkCapacityError,
)


async def _assert_capacity_rejected(pool: BoundedPasswordWorkPool) -> None:
    """Fail promptly if work was queued instead of rejected at admission."""
    candidate = asyncio.create_task(pool(lambda: "unexpected admission"))
    await asyncio.sleep(0)
    if not candidate.done():
        candidate.cancel()
        with suppress(asyncio.CancelledError):
            await candidate
        pytest.fail("password work was admitted past the configured capacity")
    with pytest.raises(PasswordWorkCapacityError):
        await candidate


async def _run_when_capacity_returns(pool: BoundedPasswordWorkPool) -> str:
    async def attempt_until_admitted() -> str:
        while True:
            try:
                result = await pool(lambda: "capacity available")
            except PasswordWorkCapacityError:
                await asyncio.sleep(0)
                continue
            assert isinstance(result, str)
            return result

    return await asyncio.wait_for(attempt_until_admitted(), timeout=1)


@pytest.mark.asyncio
async def test_cancelling_waiter_keeps_capacity_until_executor_work_finishes() -> None:
    pool = BoundedPasswordWorkPool(workers=1, queue_capacity=0)
    worker_started = threading.Event()
    release_worker = threading.Event()
    worker_returned = threading.Event()
    request: asyncio.Task[object] | None = None

    def blocked_work() -> str:
        worker_started.set()
        if not release_worker.wait(timeout=3):
            raise TimeoutError("test did not release password worker")
        worker_returned.set()
        return "finished"

    try:
        request = asyncio.create_task(pool(blocked_work))
        assert await asyncio.to_thread(worker_started.wait, 1)

        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request

        await _assert_capacity_rejected(pool)

        release_worker.set()
        assert await asyncio.to_thread(worker_returned.wait, 1)
        assert await _run_when_capacity_returns(pool) == "capacity available"
    finally:
        release_worker.set()
        if request is not None and not request.done():
            request.cancel()
            with suppress(asyncio.CancelledError):
                await request
        await pool.close()


@pytest.mark.asyncio
async def test_cancelling_before_submission_releases_capacity_exactly_once() -> None:
    pool = BoundedPasswordWorkPool(workers=1, queue_capacity=0)
    reservation_acquired = asyncio.Event()
    worker_started = threading.Event()
    release_worker = threading.Event()
    holder: asyncio.Task[None] | None = None
    worker: asyncio.Task[object] | None = None

    async def hold_without_submitting() -> None:
        async with pool.reserve():
            reservation_acquired.set()
            await asyncio.Event().wait()

    def blocked_work() -> str:
        worker_started.set()
        if not release_worker.wait(timeout=3):
            raise TimeoutError("test did not release password worker")
        return "finished"

    try:
        holder = asyncio.create_task(hold_without_submitting())
        await asyncio.wait_for(reservation_acquired.wait(), timeout=1)
        holder.cancel()
        with pytest.raises(asyncio.CancelledError):
            await holder

        worker = asyncio.create_task(pool(blocked_work))
        assert await asyncio.to_thread(worker_started.wait, 1)
        await _assert_capacity_rejected(pool)

        release_worker.set()
        assert await worker == "finished"
    finally:
        release_worker.set()
        for task in (holder, worker):
            if task is not None and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        await pool.close()


@pytest.mark.asyncio
async def test_submission_error_releases_capacity_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = BoundedPasswordWorkPool(workers=1, queue_capacity=0)
    original_submit: Callable[..., object] = pool._executor.submit
    worker_started = threading.Event()
    release_worker = threading.Event()
    worker: asyncio.Task[object] | None = None

    def reject_submission(*args: object, **kwargs: object) -> object:
        raise RuntimeError("executor rejected password work")

    def blocked_work() -> str:
        worker_started.set()
        if not release_worker.wait(timeout=3):
            raise TimeoutError("test did not release password worker")
        return "finished"

    try:
        monkeypatch.setattr(pool._executor, "submit", reject_submission)
        with pytest.raises(RuntimeError, match="executor rejected password work"):
            await pool(lambda: "not submitted")
        monkeypatch.setattr(pool._executor, "submit", original_submit)

        worker = asyncio.create_task(pool(blocked_work))
        assert await asyncio.to_thread(worker_started.wait, 1)
        await _assert_capacity_rejected(pool)

        release_worker.set()
        assert await worker == "finished"
    finally:
        release_worker.set()
        if worker is not None and not worker.done():
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
        monkeypatch.setattr(pool._executor, "submit", original_submit)
        await pool.close()


@pytest.mark.asyncio
async def test_shutdown_cancels_queued_work_and_waits_for_running_work() -> None:
    pool = BoundedPasswordWorkPool(workers=1, queue_capacity=1)
    worker_started = threading.Event()
    release_worker = threading.Event()
    queued_started = threading.Event()
    running: asyncio.Task[object] | None = None
    queued: asyncio.Task[object] | None = None
    closing: asyncio.Task[None] | None = None

    def blocked_work() -> str:
        worker_started.set()
        if not release_worker.wait(timeout=3):
            raise TimeoutError("test did not release password worker")
        return "finished"

    def queued_work() -> str:
        queued_started.set()
        return "should not run"

    try:
        running = asyncio.create_task(pool(blocked_work))
        assert await asyncio.to_thread(worker_started.wait, 1)
        queued = asyncio.create_task(pool(queued_work))
        await asyncio.sleep(0)
        assert queued.done() is False

        closing = asyncio.create_task(pool.close())
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(queued), timeout=1)
        assert queued_started.is_set() is False
        assert pool.closed is True
        assert closing.done() is False

        release_worker.set()
        assert await running == "finished"
        await asyncio.wait_for(closing, timeout=1)
    finally:
        release_worker.set()
        for task in (running, queued, closing):
            if task is not None and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        await pool.close()
