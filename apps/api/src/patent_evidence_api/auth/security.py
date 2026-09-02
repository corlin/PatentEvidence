import base64
import asyncio
import hashlib
import hmac
import secrets
import struct
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from functools import partial
from threading import Lock
from typing import Protocol

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken


SESSION_LIFETIME = timedelta(hours=12)
MFA_RECENCY = timedelta(minutes=10)
RESET_LIFETIME = timedelta(minutes=30)
RESET_RESPONSE_FLOOR_SECONDS = 0.2


def digest_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def issue_opaque_token() -> str:
    return secrets.token_urlsafe(32)


class PasswordSecurity:
    def __init__(self) -> None:
        self._hasher = PasswordHasher()
        self._dummy_hash = self._hasher.hash("not a real account password 42")

    @staticmethod
    def validate(password: str) -> None:
        if len(password) < 12 or len(password) > 128:
            raise ValueError("password_policy_failed")

    def hash(self, password: str) -> str:
        self.validate(password)
        return self._hasher.hash(password)

    def verify(self, encoded: str | None, password: str) -> bool:
        candidate = encoded or self._dummy_hash
        try:
            valid = self._hasher.verify(candidate, password)
        except (InvalidHashError, VerificationError):
            valid = False
        return bool(encoded) and valid

    def perform_dummy_work(self) -> None:
        """Run the same password KDF class for both reset-request identity branches."""
        try:
            self._hasher.verify(self._dummy_hash, "not a real account password 42")
        except VerificationError:
            pass


class PasswordWorkRunner(Protocol):
    async def __call__(
        self, function: Callable[..., object], *args: object
    ) -> object: ...


class PasswordWorkCapacityError(RuntimeError):
    """Raised before password work when the bounded pool has no free capacity."""


class _PasswordWorkPermit:
    """Release one capacity slot exactly once from any executor callback thread."""

    def __init__(self, pool: "BoundedPasswordWorkPool") -> None:
        self._pool = pool
        self._released = False
        self._lock = Lock()

    def release(self) -> None:
        with self._lock:
            if self._released:
                return
            self._released = True
        self._pool._release_capacity()


class _PasswordWorkReservation:
    def __init__(
        self, pool: "BoundedPasswordWorkPool", permit: _PasswordWorkPermit
    ) -> None:
        self._pool = pool
        self._permit = permit
        self._state = "reserved"

    def release_if_unsubmitted(self) -> None:
        if self._state != "reserved":
            return
        self._state = "released"
        self._permit.release()

    def _release_after_completion(self, _: Future[object]) -> None:
        self._permit.release()

    async def run(self, function: Callable[..., object], *args: object) -> object:
        if self._state != "reserved":
            raise RuntimeError("password work reservation has already been used")
        self._state = "submitted"
        try:
            executor_future = self._pool._executor.submit(partial(function, *args))
        except BaseException:
            self._permit.release()
            raise
        executor_future.add_done_callback(self._release_after_completion)
        wrapped_future = asyncio.wrap_future(executor_future)
        try:
            return await wrapped_future
        except asyncio.CancelledError:
            executor_future.cancel()
            raise


class BoundedPasswordWorkPool:
    """Own a dedicated password executor with bounded running and queued work."""

    def __init__(self, *, workers: int = 2, queue_capacity: int = 4) -> None:
        if not 1 <= workers <= 4:
            raise ValueError("password workers must be between 1 and 4")
        if not 0 <= queue_capacity <= 16:
            raise ValueError("password queue capacity must be between 0 and 16")
        self._executor = ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="password-work"
        )
        self._capacity = workers + queue_capacity
        self._reserved = 0
        self._closed = False
        self._state_lock = Lock()

    @property
    def closed(self) -> bool:
        with self._state_lock:
            return self._closed

    def _acquire_capacity(self) -> _PasswordWorkPermit:
        with self._state_lock:
            if self._closed or self._reserved >= self._capacity:
                raise PasswordWorkCapacityError("password work capacity exhausted")
            self._reserved += 1
        return _PasswordWorkPermit(self)

    def _release_capacity(self) -> None:
        with self._state_lock:
            if self._reserved <= 0:
                raise RuntimeError("password work capacity released more than once")
            self._reserved -= 1

    @asynccontextmanager
    async def reserve(self) -> AsyncIterator[_PasswordWorkReservation]:
        reservation = _PasswordWorkReservation(self, self._acquire_capacity())
        try:
            yield reservation
        finally:
            reservation.release_if_unsubmitted()

    async def __call__(self, function: Callable[..., object], *args: object) -> object:
        async with self.reserve() as reservation:
            return await reservation.run(function, *args)

    async def close(self) -> None:
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
        await asyncio.to_thread(self._executor.shutdown, wait=True, cancel_futures=True)


class _CallablePasswordWorkReservation:
    def __init__(self, runner: PasswordWorkRunner) -> None:
        self._runner = runner

    async def run(self, function: Callable[..., object], *args: object) -> object:
        return await self._runner(function, *args)


class ReservedPasswordSecurity:
    def __init__(
        self,
        passwords: PasswordSecurity,
        reservation: _PasswordWorkReservation | _CallablePasswordWorkReservation,
    ) -> None:
        self._passwords = passwords
        self._reservation = reservation

    async def hash(self, password: str) -> str:
        encoded = await self._reservation.run(self._passwords.hash, password)
        if not isinstance(encoded, str):
            raise TypeError("password hash runner returned an invalid result")
        return encoded

    async def verify(self, encoded: str | None, password: str) -> bool:
        return bool(
            await self._reservation.run(self._passwords.verify, encoded, password)
        )

    async def perform_dummy_work(self) -> None:
        await self._reservation.run(self._passwords.perform_dummy_work)


class AsyncPasswordSecurity:
    """Offload synchronous password KDF operations from async request handlers."""

    def __init__(
        self,
        passwords: PasswordSecurity,
        runner: PasswordWorkRunner,
    ) -> None:
        self._passwords = passwords
        self._runner = runner

    @asynccontextmanager
    async def reserve(self) -> AsyncIterator[ReservedPasswordSecurity]:
        reserve = getattr(self._runner, "reserve", None)
        if reserve is None:
            yield ReservedPasswordSecurity(
                self._passwords, _CallablePasswordWorkReservation(self._runner)
            )
            return
        async with reserve() as reservation:
            yield ReservedPasswordSecurity(self._passwords, reservation)

    async def hash(self, password: str) -> str:
        async with self.reserve() as reserved:
            return await reserved.hash(password)

    async def verify(self, encoded: str | None, password: str) -> bool:
        async with self.reserve() as reserved:
            return await reserved.verify(encoded, password)

    async def perform_dummy_work(self) -> None:
        async with self.reserve() as reserved:
            await reserved.perform_dummy_work()


class MinimumResponseTime:
    """Apply a deterministic minimum duration without exposing wall-clock tests."""

    def __init__(
        self,
        *,
        seconds: float = RESET_RESPONSE_FLOOR_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if seconds < 0:
            raise ValueError("minimum response time must not be negative")
        self._seconds = seconds
        self._monotonic = monotonic
        self._sleeper = sleeper

    def start(self) -> float:
        return self._monotonic()

    async def wait(self, started_at: float) -> None:
        remaining = self._seconds - (self._monotonic() - started_at)
        if remaining > 0:
            await self._sleeper(remaining)


class TotpSecurity:
    def __init__(self, encryption_key: str) -> None:
        self._cipher = Fernet(encryption_key.encode("ascii"))

    @staticmethod
    def issue_secret() -> str:
        return base64.b32encode(secrets.token_bytes(20)).decode("ascii")

    def encrypt(self, secret: str) -> bytes:
        return self._cipher.encrypt(secret.encode("ascii"))

    def decrypt(self, ciphertext: bytes) -> str:
        try:
            return self._cipher.decrypt(ciphertext).decode("ascii")
        except InvalidToken as exc:
            raise RuntimeError("stored MFA secret cannot be decrypted") from exc

    @staticmethod
    def verify(secret: str, code: str, now: datetime) -> bool:
        if len(code) != 6 or not code.isdigit():
            return False
        raw = base64.b32decode(secret, casefold=True)
        counter = int(now.timestamp()) // 30
        for drift in (-1, 0, 1):
            digest = hmac.new(
                raw, struct.pack(">Q", counter + drift), hashlib.sha1
            ).digest()
            offset = digest[-1] & 0x0F
            value = (
                struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
            ) % 1_000_000
            if secrets.compare_digest(f"{value:06d}", code):
                return True
        return False


class RateLimiter(Protocol):
    def allow(self, key: str, now: datetime) -> bool: ...


class DeterministicRateLimiter:
    """Process-local deterministic limiter for P0 development and tests."""

    def __init__(
        self, *, attempts: int = 4, window: timedelta = timedelta(minutes=1)
    ) -> None:
        self._attempts = attempts
        self._window = window
        self._events: dict[str, list[datetime]] = defaultdict(list)

    def allow(self, key: str, now: datetime) -> bool:
        cutoff = now - self._window
        events = [event for event in self._events[key] if event > cutoff]
        if len(events) >= self._attempts:
            self._events[key] = events
            return False
        events.append(now)
        self._events[key] = events
        return True
