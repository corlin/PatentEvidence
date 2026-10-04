"""Rule-coverage scenario: every case in fixtures/scenarios/legal-status-coverage.json.

Expected values were derived by hand from the raw source records; this test checks the
rules against them using the stored fixtures (offline). scripts/run-legal-status-scenario.py
runs the same manifest against the live sources.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from modules.legal_status.ep import assess_ep
from modules.legal_status.us import assess_us

ROOT = Path(__file__).resolve().parents[4] / "fixtures"
MANIFEST = json.loads((ROOT / "scenarios" / "legal-status-coverage.json").read_text())
AS_OF = date.fromisoformat(MANIFEST["as_of"])
OFFLINE = [c for c in MANIFEST["cases"] if c["fixture"]]


def test_manifest_covers_each_rule_once() -> None:
    ids = [c["id"] for c in MANIFEST["cases"]]
    assert len(ids) == len(set(ids)) == 17
    assert all(c.get("basis") for c in MANIFEST["cases"]), "every case must state its hand-verified basis"


@pytest.mark.parametrize("case", OFFLINE, ids=[c["id"] for c in OFFLINE])
def test_case_matches_hand_verified_expectation(case: dict) -> None:
    payload = json.loads((ROOT / "legal-status" / case["fixture"]).read_text())
    if case["publication_number"].startswith("US-"):
        result = assess_us(payload, publication_number=case["publication_number"], as_of=AS_OF)
    else:
        result = assess_ep(
            payload,
            publication_number=case["publication_number"],
            filing_date=date.fromisoformat(case["ep_filing_date"]),
            as_of=AS_OF,
        )
    expected = case["expected"]
    assert result.status == expected["status"], case["basis"]
    if "term_start" in expected:
        assert result.term.term_start.isoformat() == expected["term_start"]
    if "expiry_date" in expected:
        assert result.term.expiry_date.isoformat() == expected["expiry_date"]
    if "review_reason_contains" in expected:
        assert any(expected["review_reason_contains"] in r for r in result.review_reasons), result.review_reasons
    if "lapsed_countries" in expected:
        assert [c.country for c in result.countries if c.lapse_in_effect] == expected["lapsed_countries"]
