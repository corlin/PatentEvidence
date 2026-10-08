"""US legal-status assessment from a USPTO Open Data Portal file-wrapper record.

Rules, each grounded in measured ODP data (see the 2026-10-04 spike and
ADR 0005) and in statute (to be confirmed by qualified counsel):

- Term start (35 U.S.C. §154(a)(2)): the earliest filing date among the
  application itself and its continuation (CON), divisional (DIV),
  continuation-in-part (CIP) and national-stage (NST, i.e. the PCT
  international filing date) parents. Provisional parents (PRO) and foreign
  priority (§154(a)(3)) do not start the term. These five codes are the ones
  ODP returned across the 60-patent sample.
- Term: 20 years plus patent term adjustment (§154(b)), ODP
  ``adjustmentTotalQuantity``. On the expiry date itself the patent is still
  treated as presumed in force; it is expired only when ``as_of`` is later.
- Lapse for non-payment of maintenance fees (§41(b), 37 CFR 1.362): ODP
  status text "Patent Expired Due to NonPayment of Maintenance Fees ...",
  corroborated by the ``EXP.`` event (the two agreed on all 16 lapsed sample
  patents).

- Reissues (``applicationTypeCategory`` "REISSUE"): under 35 U.S.C. §251 a
  reissued patent runs for the unexpired part of the *original* patent's term,
  which this record does not give. Until the original is looked up, a reissue
  that is not explicitly lapsed is ``undetermined``.

Uncertainty resolves toward keeping the patent in the risk set (presumed in
force or undetermined, with a review reason). For FTO, wrongly treating a live
patent as dead is the costly error.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from modules.legal_status.models import (
    LegalStatusAssessment,
    Status,
    StatusEvidence,
    TermComputation,
)

SOURCE = "USPTO ODP"
TERM_PARENT_CODES = {"CON", "DIV", "CIP", "NST"}
LAPSED_STATUS_MARKER = "Expired Due to NonPayment of Maintenance Fees"
IN_FORCE_STATUS = "Patented Case"
TERMINAL_DISCLAIMER_CODES = {"DIST", "P574"}
EXPIRY_EVENT = "EXP."
# Maintenance-fee and related events kept as evidence (codes as seen in ODP).
EVIDENCE_EVENT_PREFIXES = ("M155", "M255", "M355", "EXP", "REM")


def parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def add_years(day: date, years: int) -> date:
    """Calendar-year addition; 29 Feb maps to 28 Feb in non-leap target years."""
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(year=day.year + years, day=28)


def term_start(record: dict[str, Any]) -> tuple[date | None, str]:
    meta = record.get("applicationMetaData") or {}
    own = parse_date(meta.get("filingDate"))
    candidates: list[tuple[date, str]] = []
    if own:
        candidates.append((own, f"own filing date {own.isoformat()}"))
    for parent in record.get("parentContinuityBag") or []:
        code = parent.get("claimParentageTypeCode")
        parent_date = parse_date(parent.get("parentApplicationFilingDate"))
        if code in TERM_PARENT_CODES and parent_date:
            candidates.append(
                (
                    parent_date,
                    f"{code} parent {parent.get('parentApplicationNumberText')} "
                    f"filed {parent_date.isoformat()}",
                )
            )
    if not candidates:
        return None, "no filing date"
    return min(candidates, key=lambda item: item[0])


def assess_us(
    record: dict[str, Any], *, publication_number: str, as_of: date
) -> LegalStatusAssessment:
    meta = record.get("applicationMetaData") or {}
    status_text = meta.get("applicationStatusDescriptionText") or ""
    events = record.get("eventDataBag") or []
    event_codes = {e.get("eventCode") for e in events}

    evidence: list[StatusEvidence] = [
        StatusEvidence(
            SOURCE,
            "STATUS",
            status_text,
            parse_date(meta.get("applicationStatusDate")),
        )
    ]
    for event in events:
        code = event.get("eventCode") or ""
        if code.startswith(EVIDENCE_EVENT_PREFIXES) or code in TERMINAL_DISCLAIMER_CODES:
            evidence.append(
                StatusEvidence(
                    SOURCE,
                    code,
                    event.get("eventDescriptionText") or "",
                    parse_date(event.get("eventDate")),
                )
            )

    reasons: list[str] = []
    grant = parse_date(meta.get("grantDate"))
    start, basis = term_start(record)
    pta = (record.get("patentTermAdjustmentData") or {}).get("adjustmentTotalQuantity")

    term: TermComputation | None = None
    if start is not None:
        expiry = add_years(start, 20) + timedelta(days=int(pta or 0))
        term = TermComputation(start, basis, 20, int(pta or 0), expiry)

    def result(status: Status) -> LegalStatusAssessment:
        return LegalStatusAssessment(
            jurisdiction="US",
            publication_number=publication_number,
            as_of=as_of,
            status=status,
            term=term,
            evidence=tuple(evidence),
            review_reasons=tuple(reasons),
            data_as_of=record.get("lastIngestionDateTime"),
        )

    if grant is None:
        reasons.append("not granted according to ODP (no grant date)")
        return result("undetermined")

    expiry_event_dates = [
        parse_date(e.get("eventDate")) for e in events if e.get("eventCode") == EXPIRY_EVENT
    ]
    if LAPSED_STATUS_MARKER in status_text:
        if EXPIRY_EVENT not in event_codes:
            reasons.append("lapsed status without EXP. event")
        elif all(d is not None and d > as_of for d in expiry_event_dates):
            # The lapse was recorded after the analysis date; ODP holds only the current status.
            reasons.append("lapse recorded after the analysis date; status at that date inferred from term")
            return result("presumed_in_force" if term and as_of <= term.expiry_date else "undetermined")
        return result("lapsed")
    if EXPIRY_EVENT in event_codes:
        reasons.append("EXP. event present but status is not lapsed (possible reinstatement)")
        return result("undetermined")
    if (meta.get("applicationTypeCategory") or "").upper() == "REISSUE":
        reasons.append(
            "reissue: the term follows the original patent (35 U.S.C. §251), which is not looked up yet"
        )
        return result("undetermined")
    if status_text != IN_FORCE_STATUS:
        reasons.append(f"unrecognised ODP status: {status_text!r}")
        return result("undetermined")

    if term is None:
        reasons.append("no filing date: term cannot be computed")
        return result("undetermined")
    if pta is None:
        reasons.append("patent term adjustment unknown: expiry date is a lower bound")
    if event_codes & TERMINAL_DISCLAIMER_CODES:
        reasons.append("terminal disclaimer: may expire earlier, with the referenced patent")

    if as_of > term.expiry_date:
        if pta is None:
            # The real expiry may be later than the lower bound; do not declare it dead.
            return result("presumed_in_force")
        return result("expired")
    return result("presumed_in_force")
