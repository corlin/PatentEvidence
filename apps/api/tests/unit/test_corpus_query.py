"""US/EP corpus scope, query and row normalization (ADR 0007)."""

from __future__ import annotations

from datetime import date

import pytest

from modules.corpus.query import CorpusScope, build_corpus_query, query_sha256, row_to_member

SCOPE = CorpusScope(as_of=date(2026, 10, 4))


def test_cutoffs_follow_statute_plus_margin() -> None:
    assert SCOPE.cutoff("US") == date(2001, 10, 4)  # 20 years + 5-year PTA margin
    assert SCOPE.cutoff("EP") == date(2006, 10, 4)  # 20 years, no margin
    record = SCOPE.as_record()
    assert record["us_filing_date_cutoff"] == "2001-10-04"
    assert record["ep_filing_date_cutoff"] == "2006-10-04"


def test_query_encodes_scope_and_is_deterministic() -> None:
    sql = build_corpus_query(SCOPE)
    assert sql == build_corpus_query(CorpusScope(as_of=date(2026, 10, 4)))
    assert query_sha256(sql) == query_sha256(build_corpus_query(SCOPE))
    assert "p.kind_code IN ('B1', 'B2', 'E1')" in sql
    assert "p.kind_code IN ('B1', 'B2', 'B3')" in sql
    assert "p.filing_date >= 20011004" in sql and "p.filing_date >= 20061004" in sql
    # Classification scope is CPC OR IPC (CPC alone misses IPC-only documents).
    assert "STARTS_WITH(c.code, 'H01M')" in sql and "STARTS_WITH(i.code, 'H02J')" in sql
    assert "inventor" not in sql  # inventors are deliberately not loaded


def test_different_dates_produce_different_queries() -> None:
    other = build_corpus_query(CorpusScope(as_of=date(2027, 1, 1)))
    assert query_sha256(other) != query_sha256(build_corpus_query(SCOPE))


def test_unsafe_literals_are_rejected() -> None:
    with pytest.raises(ValueError):
        build_corpus_query(CorpusScope(as_of=date(2026, 10, 4), us_kinds=("B1'; DROP",)))


def _row(**overrides):
    row = {
        "publication_number": "US-7252747-B2", "country_code": "US", "kind_code": "B2",
        "application_number": "US-54369206-A", "family_id": "37000000", "filing_date": 20061005,
        "grant_date": 20070807, "priority_date": 0, "cpc_codes": ["H01M10/0525"], "ipc_codes": [],
        "assignees_original": ["EXAMPLE CORP"], "assignees_harmonized": ["EXAMPLE CORP"],
        "title_en": "Battery", "title_original": None, "cpc_match": True, "ipc_match": False,
    }
    row.update(overrides)
    return row


def test_row_normalization() -> None:
    member = row_to_member(_row())
    assert member["filing_date"] == date(2006, 10, 5)
    assert member["grant_date"] == date(2007, 8, 7)
    assert member["priority_date"] is None  # 0 means unknown in BigQuery
    assert member["scope_match"] == "cpc"
    assert member["jurisdiction"] == "US" and member["kind"] == "B2"
    assert row_to_member(_row(ipc_match=True))["scope_match"] == "both"
    assert row_to_member(_row(cpc_match=False, ipc_match=True))["scope_match"] == "ipc"


def test_row_outside_scope_is_rejected() -> None:
    with pytest.raises(ValueError):
        row_to_member(_row(cpc_match=False, ipc_match=False))
