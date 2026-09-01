import base64
import hashlib
import hmac
import secrets
import struct
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Protocol

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken


SESSION_LIFETIME = timedelta(hours=12)
MFA_RECENCY = timedelta(minutes=10)
RESET_LIFETIME = timedelta(minutes=30)


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
