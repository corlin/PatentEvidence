"""Legal-status assessment results (ADR 0005, stage 2).

An assessment never asserts more than its evidence supports:

- ``presumed_in_force`` means "no lapse or expiry found in the source data as
  of ``data_as_of``". It does not mean "valid": court or office invalidation,
  licensing and similar facts are outside these sources.
- Anything the rules cannot decide is ``undetermined`` with explicit
  ``review_reasons``; it is never silently treated as in force or as dead.
- Every assessment carries the raw events it relied on, the source, the
  data snapshot time and the analysis date, so it can be sealed into an
  evidence snapshot and re-checked later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

Status = Literal["presumed_in_force", "lapsed", "expired", "undetermined"]


@dataclass(frozen=True)
class StatusEvidence:
    source: str  # e.g. "USPTO ODP", "EPO OPS INPADOC"
    code: str
    description: str
    event_date: date | None
    detail: str = ""


@dataclass(frozen=True)
class TermComputation:
    """How the expiry date was derived, so a reviewer can redo the arithmetic."""

    term_start: date
    term_start_basis: str
    statutory_years: int
    adjustment_days: int
    expiry_date: date


@dataclass(frozen=True)
class CountryStatus:
    """EP only: evidence per contracting state, without inferring validity."""

    country: str
    lapsed_on: date | None = None
    lapse_reason: str = ""
    reinstated_on: date | None = None
    last_fee_year: int | None = None
    last_fee_paid_on: date | None = None

    @property
    def lapse_in_effect(self) -> bool:
        if self.lapsed_on is None:
            return False
        return self.reinstated_on is None or self.reinstated_on < self.lapsed_on


@dataclass(frozen=True)
class LegalStatusAssessment:
    jurisdiction: Literal["US", "EP"]
    publication_number: str
    as_of: date
    status: Status
    term: TermComputation | None
    evidence: tuple[StatusEvidence, ...]
    review_reasons: tuple[str, ...] = ()
    data_as_of: str | None = None  # source snapshot / ingestion timestamp
    countries: tuple[CountryStatus, ...] = field(default=())
