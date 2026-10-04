#!/usr/bin/env python3
"""Run the legal-status rule-coverage scenario against the live sources.

Reads fixtures/scenarios/legal-status-coverage.json, fetches each patent from
USPTO ODP / EPO OPS, assesses it with the current rules and compares the result
with the hand-verified expectation. About 17 API calls, no BigQuery.

  .venv/bin/python scripts/run-legal-status-scenario.py            # compare only
  .venv/bin/python scripts/run-legal-status-scenario.py --record   # also store results

Needs PATENT_EVIDENCE_USPTO_API_KEY and PATENT_EVIDENCE_EPO_CLIENT_ID/SECRET;
--record also needs PATENT_EVIDENCE_WORKER_DATABASE_URL. Exit code 1 if any case
differs from its expectation (live data can change; a difference is reported,
not hidden).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "apps" / "api" / "src"), str(ROOT / "apps" / "worker" / "src")]

from adapters.legal_status.clients import EpoOpsLegalClient, UsptoOdpClient  # noqa: E402
from modules.legal_status.ep import assess_ep  # noqa: E402
from modules.legal_status.serialize import ep_extract, us_extract  # noqa: E402
from modules.legal_status.us import assess_us  # noqa: E402

MANIFEST = ROOT / "fixtures" / "scenarios" / "legal-status-coverage.json"


def compare(expected: dict, outcome: str, result) -> list[str]:
    problems: list[str] = []
    if "outcome" in expected:
        if outcome != expected["outcome"]:
            problems.append(f"outcome {outcome} != {expected['outcome']}")
        return problems
    if result is None:
        return [f"outcome {outcome}, expected a status"]
    if result.status != expected["status"]:
        problems.append(f"status {result.status} != {expected['status']}")
    if "term_start" in expected and result.term.term_start.isoformat() != expected["term_start"]:
        problems.append(f"term_start {result.term.term_start} != {expected['term_start']}")
    if "expiry_date" in expected and result.term.expiry_date.isoformat() != expected["expiry_date"]:
        problems.append(f"expiry {result.term.expiry_date} != {expected['expiry_date']}")
    if "review_reason_contains" in expected and not any(
        expected["review_reason_contains"] in r for r in result.review_reasons
    ):
        problems.append(f"missing review reason {expected['review_reason_contains']!r}")
    if "lapsed_countries" in expected:
        lapsed = [c.country for c in result.countries if c.lapse_in_effect]
        if lapsed != expected["lapsed_countries"]:
            problems.append(f"lapsed {lapsed} != {expected['lapsed_countries']}")
    return problems


async def run(record: bool) -> int:
    manifest = json.loads(MANIFEST.read_text())
    as_of = date.fromisoformat(manifest["as_of"])
    odp, ops = UsptoOdpClient(), EpoOpsLegalClient()
    refresher = None
    if record:
        from adapters.object_storage.client import ObjectStorageClient
        from patent_evidence_api.core.database import create_engine, create_worker_session_factory
        from patent_evidence_api.core.settings import Settings
        from patent_evidence_worker.legal_status_refresh import LegalStatusRefresher

        engine = create_engine(Settings().worker_database_url)
        refresher = LegalStatusRefresher(
            create_worker_session_factory(engine), ObjectStorageClient(), odp=odp, ops=ops
        )
    failures = 0
    try:
        for case in manifest["cases"]:
            number = case["publication_number"]
            country, num, kind = number.split("-")
            filing = date.fromisoformat(case["ep_filing_date"]) if case.get("ep_filing_date") else None
            if country == "US":
                response = await odp.file_wrapper_response(num)
                result = assess_us(us_extract(response.data), publication_number=number, as_of=as_of) if response.data else None
            else:
                response = await ops.legal_response(country, num, kind)
                result = (
                    assess_ep(ep_extract(response.data), publication_number=number, filing_date=filing, as_of=as_of)
                    if response.data
                    else None
                )
                time.sleep(1.2)  # stay well inside the OPS throttle
            outcome = "found" if response.data else "not_found"
            problems = compare(case["expected"], outcome, result)
            failures += bool(problems)
            shown = result.status if result else outcome
            print(f"{'OK  ' if not problems else 'DIFF'} {case['id']:<34} {number:<16} {shown:<18} {'; '.join(problems)}")
            if refresher is not None:
                stored = await refresher.refresh(number, as_of=as_of, ep_filing_date=filing)
                print(f"     recorded source_record={stored.source_record_id} assessment={stored.assessment_id}")
    finally:
        await odp.aclose()
        await ops.aclose()
        if refresher is not None:
            await engine.dispose()
    print(f"\n{len(manifest['cases']) - failures}/{len(manifest['cases'])} cases match (as of {as_of}, run {datetime.now(UTC).isoformat(timespec='seconds')})")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--record", action="store_true", help="also store records and assessments in the database")
    return asyncio.run(run(parser.parse_args().record))


if __name__ == "__main__":
    raise SystemExit(main())
