from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

AuditResult = Literal["allowed", "denied", "failed"]


@dataclass(frozen=True)
class PlatformAuditEvent:
    actor_identity_id: UUID | None
    action: str
    target_type: str
    target_id: UUID | None
    result: AuditResult
    request_correlation_id: str
    safe_summary: str


class PlatformAuditWriter:
    """Append secret-safe platform audit evidence with one field policy."""

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock

    async def append(self, session: AsyncSession, event: PlatformAuditEvent) -> None:
        await session.execute(
            text(
                """INSERT INTO platform_audit_events
                (id,actor_identity_id,action,target_type,target_id,result,
                 request_correlation_id,safe_summary,created_at)
                VALUES (:id,:actor,:action,:target_type,:target,:result,
                        :correlation,:summary,:now)"""
            ),
            {
                "id": uuid4(),
                "actor": event.actor_identity_id,
                "action": event.action,
                "target_type": event.target_type,
                "target": event.target_id,
                "result": event.result,
                "correlation": event.request_correlation_id[:128],
                "summary": event.safe_summary[:500],
                "now": self._clock(),
            },
        )
