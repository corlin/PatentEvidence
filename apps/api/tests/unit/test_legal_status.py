"""Legal-status rules (ADR 0005 stage 2) against real public US/EP records."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from modules.legal_status.ep import assess_ep, designated_states_at_grant, parse_inpadoc
from modules.legal_status.us import add_years, assess_us

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures" / "legal-status"
AS_OF = date(2026, 10, 4)


def _us(number: str) -> dict:
    return json.loads((FIXTURES / "us" / f"US-{number}.json").read_text())


def _ep(publication: str) -> dict:
    return json.loads((FIXTURES / "ep" / f"{publication}.json").read_text())


# ------------------------------------------------------------------- US


def test_us_divisional_term_runs_from_the_parent_filing_date() -> None:
    """Own filing 2006-10-05, but a DIV of an application filed 2003-07-25."""
    result = assess_us(_us("7252747"), publication_number="US-7252747-B2", as_of=AS_OF)
    assert result.term is not None
    assert result.term.term_start == date(2003, 7, 25)
    assert result.term.term_start_basis.startswith("DIV parent")
    assert result.term.expiry_date == date(2023, 7, 25)
    # ODP still says "Patented Case": its status does not flip when the term ends.
    assert result.evidence[0].description == "Patented Case"
    assert result.status == "expired"


def test_us_national_stage_term_runs_from_the_pct_filing_date() -> None:
    result = assess_us(_us("7427369"), publication_number="US-7427369-B2", as_of=AS_OF)
    assert result.term.term_start == date(2001, 6, 15)
    assert result.term.term_start_basis.startswith("NST parent")
    assert result.status == "expired"


def test_us_provisional_parent_does_not_start_the_term() -> None:
    record = _us("10615417")
    assert {p["claimParentageTypeCode"] for p in record["parentContinuityBag"]} == {"PRO"}
    result = assess_us(record, publication_number="US-10615417-B2", as_of=AS_OF)
    assert result.term.term_start == date(2018, 5, 15)
    assert result.term.term_start_basis.startswith("own filing date")
    assert result.status == "presumed_in_force"


def test_us_maintenance_fee_lapse_is_evidenced() -> None:
    result = assess_us(_us("7303424"), publication_number="US-7303424-B2", as_of=AS_OF)
    assert result.status == "lapsed"
    assert "EXP." in {e.code for e in result.evidence}
    assert result.review_reasons == ()


def test_us_lapse_recorded_after_the_analysis_date_is_not_applied() -> None:
    record = _us("7303424")
    exp_date = min(
        date.fromisoformat(e["eventDate"]) for e in record["eventDataBag"] if e["eventCode"] == "EXP."
    )
    before = assess_us(
        record, publication_number="US-7303424-B2", as_of=date(exp_date.year - 1, 1, 1)
    )
    assert before.status == "presumed_in_force"
    assert any("after the analysis date" in r for r in before.review_reasons)


def test_us_term_adds_patent_term_adjustment() -> None:
    result = assess_us(_us("8623541"), publication_number="US-8623541-B2", as_of=AS_OF)
    assert result.term.term_start == date(2009, 3, 7)  # PCT/KR2009/001143
    assert result.term.adjustment_days == 580
    assert result.term.expiry_date == date(2030, 10, 8)


def test_us_terminal_disclaimer_is_flagged_not_guessed() -> None:
    result = assess_us(_us("8623541"), publication_number="US-8623541-B2", as_of=AS_OF)
    assert result.status == "presumed_in_force"
    assert any("terminal disclaimer" in r for r in result.review_reasons)


def test_us_unknown_adjustment_never_declares_expiry_early() -> None:
    record = _us("12107219")
    assert record["patentTermAdjustmentData"] is None
    result = assess_us(record, publication_number="US-12107219-B2", as_of=AS_OF)
    assert result.status == "presumed_in_force"
    assert any("adjustment unknown" in r for r in result.review_reasons)
    # Past the lower-bound expiry, it is still not declared expired.
    later = assess_us(record, publication_number="US-12107219-B2", as_of=date(2044, 1, 1))
    assert later.status == "presumed_in_force"


def test_us_expiry_day_itself_is_still_in_force() -> None:
    record = _us("12630442")
    expiry = assess_us(record, publication_number="US-12630442-B2", as_of=AS_OF).term.expiry_date
    assert assess_us(record, publication_number="x", as_of=expiry).status == "presumed_in_force"
    later = date.fromordinal(expiry.toordinal() + 1)
    assert assess_us(record, publication_number="x", as_of=later).status == "expired"


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda r: r["applicationMetaData"].update(grantDate=None), "not granted"),
        (
            lambda r: r["applicationMetaData"].update(applicationStatusDescriptionText="Withdrawn"),
            "unrecognised ODP status",
        ),
        (
            lambda r: r["eventDataBag"].append(
                {"eventCode": "EXP.", "eventDescriptionText": "Expire Patent", "eventDate": "2020-01-01"}
            ),
            "possible reinstatement",
        ),
    ],
)
def test_us_inconsistent_records_are_undetermined(mutate, reason: str) -> None:
    record = _us("12630442")
    mutate(record)
    result = assess_us(record, publication_number="x", as_of=AS_OF)
    assert result.status == "undetermined"
    assert any(reason in r for r in result.review_reasons)


def test_add_years_handles_29_february() -> None:
    assert add_years(date(2024, 2, 29), 20) == date(2044, 2, 29)
    assert add_years(date(2024, 2, 29), 1) == date(2025, 2, 28)


# ------------------------------------------------------------------- EP


def test_ep_parses_designations_lapses_and_fees() -> None:
    events = parse_inpadoc(_ep("EP-1801605-B1"))
    assert designated_states_at_grant(events) == ["DE", "FR", "GB"]
    pg25 = {e.country: e for e in events if e.code == "PG25"}
    assert pg25["FR"].effective_date == date(2017, 1, 2)
    assert pg25["FR"].fields["Free Format Text"] == "LAPSE BECAUSE OF NON-PAYMENT OF DUE FEES"
    gbpc = next(e for e in events if e.code == "GBPC")
    assert gbpc.country == "GB"  # named in the description, not in a Ref Country Code line
    fees = {e.country: e.fields["Year of Fee Payment"] for e in events if e.code == "PGFP"}
    assert fees == {"GB": "10", "DE": "10", "FR": "10"}


@pytest.mark.parametrize(
    ("as_of", "status", "lapsed"),
    [
        (date(2016, 1, 1), "presumed_in_force", []),
        (date(2016, 12, 23), "presumed_in_force", ["GB"]),
        (date(2017, 1, 3), "presumed_in_force", ["FR", "GB"]),
        (date(2017, 7, 1), "lapsed", ["DE", "FR", "GB"]),
    ],
)
def test_ep_status_follows_the_lapse_timeline(as_of: date, status: str, lapsed: list[str]) -> None:
    result = assess_ep(
        _ep("EP-1801605-B1"), publication_number="EP-1801605-B1", filing_date=date(2006, 12, 22), as_of=as_of
    )
    assert result.status == status
    assert [c.country for c in result.countries if c.lapse_in_effect] == lapsed


def test_ep_reinstatement_then_later_lapse() -> None:
    def italy(as_of: date):
        result = assess_ep(
            _ep("EP-1942544-B1"), publication_number="EP-1942544-B1", filing_date=date(2006, 12, 18), as_of=as_of
        )
        return result, {c.country: c for c in result.countries}["IT"]

    _, it_2012 = italy(date(2012, 1, 1))
    assert it_2012.reinstated_on == date(2011, 5, 1)
    assert not it_2012.lapse_in_effect
    result, it_now = italy(AS_OF)
    assert it_now.lapsed_on == date(2015, 12, 18)
    assert it_now.lapse_in_effect
    assert result.status == "lapsed"


def test_ep_fee_evidence_keeps_it_presumed_in_force_until_term_end() -> None:
    result = assess_ep(
        _ep("EP-1819002-B1"), publication_number="EP-1819002-B1", filing_date=date(2007, 1, 31), as_of=AS_OF
    )
    assert result.status == "presumed_in_force"
    de = {c.country: c for c in result.countries}["DE"]
    assert de.last_fee_year == 20 and not de.lapse_in_effect
    assert result.term.expiry_date == date(2027, 1, 31)
    expired = assess_ep(
        _ep("EP-1819002-B1"), publication_number="EP-1819002-B1", filing_date=date(2007, 1, 31), as_of=date(2027, 2, 1)
    )
    assert expired.status == "expired"


def test_ep_states_without_any_report_are_flagged_not_assumed() -> None:
    result = assess_ep(
        _ep("EP-2277223-B1"), publication_number="EP-2277223-B1", filing_date=date(2009, 5, 5), as_of=AS_OF
    )
    assert result.status == "presumed_in_force"
    assert any("no national events reported for: LI" in r for r in result.review_reasons)


def test_ep_unitary_effect_is_not_inferred_lapsed_from_national_events() -> None:
    result = assess_ep(
        _ep("EP-3467934-B1"), publication_number="EP-3467934-B1", filing_date=date(2017, 5, 22), as_of=AS_OF
    )
    assert result.status == "presumed_in_force"
    assert any("unitary effect" in r for r in result.review_reasons)


def test_ep_unknown_negative_event_without_state_is_undetermined() -> None:
    payload = _ep("EP-1819002-B1")
    payload["ops:legal"].append(
        {"@code": "ZZZZ", "@desc": "SOMETHING NEGATIVE AT EP LEVEL", "@infl": "-", "ops:pre": [],
         "ops:L007EP": {"$": "2020-01-01"}}
    )
    result = assess_ep(payload, publication_number="x", filing_date=date(2007, 1, 31), as_of=AS_OF)
    assert result.status == "undetermined"
    assert any("ZZZZ" in r for r in result.review_reasons)


def test_ep_without_grant_designations_is_undetermined() -> None:
    payload = _ep("EP-1801605-B1")
    payload["ops:legal"] = [e for e in payload["ops:legal"] if e["@code"].strip() != "AK"]
    result = assess_ep(payload, publication_number="x", filing_date=date(2006, 12, 22), as_of=date(2016, 1, 1))
    assert result.status == "undetermined"
