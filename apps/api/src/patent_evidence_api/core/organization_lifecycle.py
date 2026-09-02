from datetime import datetime
from typing import Any


class OrganizationLifecycle:
    """Apply one lifecycle rule to reads, authorization, and mutations."""

    @staticmethod
    def effective_status(
        persisted_status: str, expires_at: datetime | None, now: datetime
    ) -> str:
        if expires_at is not None and expires_at <= now:
            return "expired"
        return persisted_status

    def organization_view(self, row: dict[str, Any], now: datetime) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "slug": row["slug"],
            "display_name": row["display_name"],
            "status": self.effective_status(row["status"], row["expires_at"], now),
            "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
            "created_at": row["created_at"].isoformat(),
        }

    def quota_view(self, row: dict[str, Any], now: datetime) -> dict[str, Any]:
        organization_status = self.effective_status(
            row["status"], row["expires_at"], now
        )
        effective_status = (
            organization_status
            if organization_status in {"suspended", "expired"}
            else row["quota_status"]
        )
        return {
            "plan_key": row["plan_key"],
            "monthly_case_allowance": row["monthly_case_allowance"],
            "current_period_start": row["current_period_start"].isoformat(),
            "current_period_end": row["current_period_end"].isoformat(),
            "status": effective_status,
        }
