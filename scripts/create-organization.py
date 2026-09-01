#!/usr/bin/env python3
"""Thin HTTP client for the platform organization-provisioning API."""

import argparse
import json
import os
import sys

import httpx


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(
        description="Create an organization through the platform API"
    )
    command.add_argument("--api-url", required=True)
    command.add_argument("--idempotency-key", required=True)
    command.add_argument("--slug", required=True)
    command.add_argument("--display-name", required=True)
    command.add_argument("--admin-email", required=True)
    command.add_argument("--plan-key", required=True)
    command.add_argument("--monthly-case-allowance", required=True, type=int)
    command.add_argument("--current-period-start", required=True)
    command.add_argument("--current-period-end", required=True)
    command.add_argument("--expires-at")
    return command


def main() -> int:
    arguments = parser().parse_args()
    session_token = os.environ.get("PATENT_EVIDENCE_SESSION_TOKEN")
    if not session_token:
        print("PATENT_EVIDENCE_SESSION_TOKEN is required", file=sys.stderr)
        return 2
    payload = {
        "slug": arguments.slug,
        "display_name": arguments.display_name,
        "admin_email": arguments.admin_email,
        "plan_key": arguments.plan_key,
        "monthly_case_allowance": arguments.monthly_case_allowance,
        "current_period_start": arguments.current_period_start,
        "current_period_end": arguments.current_period_end,
        "expires_at": arguments.expires_at,
    }
    try:
        response = httpx.post(
            f"{arguments.api_url.rstrip('/')}/api/v1/platform/organizations",
            json=payload,
            headers={"Idempotency-Key": arguments.idempotency_key},
            cookies={"pe_session": session_token},
            timeout=30,
        )
    except httpx.HTTPError as error:
        print(f"organization request failed: {error}", file=sys.stderr)
        return 1
    if response.status_code not in (200, 201):
        print(
            f"organization request rejected ({response.status_code})", file=sys.stderr
        )
        return 1
    print(json.dumps(response.json(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
