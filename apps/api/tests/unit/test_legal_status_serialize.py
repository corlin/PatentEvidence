"""Extract trimming and canonical hashing for stored assessments (ADR 0006)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from modules.legal_status.serialize import (
    RULES_VERSION,
    assessment_to_dict,
    content_sha256,
    ep_extract,
    us_extract,
)
from modules.legal_status.us import assess_us

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures" / "legal-status"


def test_extracts_are_idempotent_on_the_approved_fixtures() -> None:
    """The fixtures were produced by the same trimming, so extracting them again is a no-op."""
    for path in (FIXTURES / "us").glob("*.json"):
        record = json.loads(path.read_text())
        assert us_extract(record) == record, path.name
    for path in (FIXTURES / "ep").glob("*.json"):
        payload = json.loads(path.read_text())
        assert ep_extract(payload) == payload, path.name


def test_us_extract_drops_fields_the_rules_do_not_read() -> None:
    record = json.loads((FIXTURES / "us" / "US-7252747.json").read_text())
    record["inventorBag"] = [{"firstName": "A", "lastName": "B"}]
    record["eventDataBag"].append({"eventCode": "CTNF", "eventDescriptionText": "Non-Final Rejection"})
    extract = us_extract(record)
    assert "inventorBag" not in extract
    assert all(e["eventCode"] != "CTNF" for e in extract["eventDataBag"])


def test_content_hash_is_stable_and_sensitive() -> None:
    record = json.loads((FIXTURES / "us" / "US-7252747.json").read_text())
    a = assess_us(record, publication_number="US-7252747-B2", as_of=date(2026, 10, 4))
    b = assess_us(record, publication_number="US-7252747-B2", as_of=date(2026, 10, 4))
    assert content_sha256(a) == content_sha256(b)
    c = assess_us(record, publication_number="US-7252747-B2", as_of=date(2020, 1, 1))
    assert content_sha256(a) != content_sha256(c)
    body = assessment_to_dict(a)
    assert body["rules_version"] == RULES_VERSION
    assert body["term"]["expiry_date"] == "2023-07-25"
