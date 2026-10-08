"""EP legal-status assessment from EPO OPS INPADOC legal events.

Grounded in the events OPS returned for 57 sampled EP grants (2026-10-04):

- Per contracting state, national post-grant information arrives as events
  whose ``ops:pre`` lines carry ``Ref Country Code XX``, ``Effective DATE``,
  ``Free Format Text`` and, for fees, ``Year of Fee Payment``. Some national
  codes instead name the state in the description (``GB: ...``, ``BE: ...``).
- OPS marks each event ``@infl`` "+" (positive) or "-" (negative). A negative
  event naming a state is treated as a lapse there; ``PGRI`` reinstates.
- The grant-time designated states come from the ``AK`` event of the B
  document ("Designated State(s) DE FR GB ...").
- Term: 20 years from the filing date (EPC Art. 63).

What is *not* inferred: validity in a state with no events, and lapse of a
unitary patent from national events (unitary effect is flagged instead).
Unknown negative events without a state make the result ``undetermined``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from modules.legal_status.models import (
    CountryStatus,
    LegalStatusAssessment,
    Status,
    StatusEvidence,
    TermComputation,
)
from modules.legal_status.us import add_years, parse_date

SOURCE = "EPO OPS INPADOC"
REINSTATEMENT_CODES = {"PGRI"}
FEE_CODES = {"PGFP"}
UNITARY_PREFIX = "U"  # e.g. U20: renewal fee for the European patent with unitary effect paid
GRANT_KINDS = {"B1", "B2", "B3"}

_COUNTRY_IN_DESC = re.compile(r"^([A-Z]{2}):")
_PREFIX = re.compile(r"^.*?\d{4}-\d{2}-\d{2}\S*?[+\- ]")
_PRE_FIELD = re.compile(
    r"(Ref Country Code|Effective DATE|Free Format Text|Payment DATE|Year of Fee Payment|"
    r"Kind Code of Ref Document|Designated State\(s\))\s+(.*)$"
)


@dataclass(frozen=True)
class LegalEvent:
    code: str
    description: str
    influence: str  # "+", "-" or " "
    gazette_date: date | None
    fields: dict[str, str] = field(default_factory=dict)
    lines: tuple[str, ...] = ()

    @property
    def country(self) -> str | None:
        if self.fields.get("Ref Country Code"):
            return self.fields["Ref Country Code"].strip()[:2]
        match = _COUNTRY_IN_DESC.match(self.description)
        return match.group(1) if match else None

    @property
    def effective_date(self) -> date | None:
        return _yyyymmdd(self.fields.get("Effective DATE")) or self.gazette_date


def _yyyymmdd(value: str | None) -> date | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)[:8]
    try:
        return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
    except (ValueError, IndexError):
        return None


def parse_inpadoc(payload: dict[str, Any]) -> list[LegalEvent]:
    """Flatten an OPS ``legal`` JSON response into events (pure function)."""
    raw: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "ops:legal" in node:
                items = node["ops:legal"]
                raw.extend(items if isinstance(items, list) else [items])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    events: list[LegalEvent] = []
    for item in raw:
        pre = item.get("ops:pre") or []
        pre = pre if isinstance(pre, list) else [pre]
        lines: list[str] = []
        fields: dict[str, str] = {}
        desc = str(item.get("@desc", ""))
        for entry in pre:
            text = str(entry.get("$", ""))
            # Each line is "<fixed-width prefix><code><infl><description> <payload>";
            # the description is repeated verbatim, so keep what follows it.
            idx = text.find(desc) if desc else -1
            tail = text[idx + len(desc) :] if idx >= 0 else _PREFIX.sub("", text)
            tail = tail.strip()
            lines.append(tail)
            match = _PRE_FIELD.search(tail)
            if match:
                key, value = match.group(1), match.group(2).strip()
                fields[key] = f"{fields[key]} {value}".strip() if key in fields else value
        events.append(
            LegalEvent(
                code=str(item.get("@code", "")).strip(),
                description=str(item.get("@desc", "")).strip(),
                influence=str(item.get("@infl", " ")),
                gazette_date=parse_date((item.get("ops:L007EP") or {}).get("$")),
                fields=fields,
                lines=tuple(lines),
            )
        )
    return events


def designated_states_at_grant(events: list[LegalEvent]) -> list[str]:
    """States from the AK event of the granted (B) document, in listed order."""
    states: list[str] = []
    for event in events:
        if event.code != "AK":
            continue
        if event.fields.get("Kind Code of Ref Document", "").strip() not in GRANT_KINDS:
            continue
        states.extend(
            t for t in event.fields.get("Designated State(s)", "").split() if re.fullmatch(r"[A-Z]{2}", t)
        )
    return list(dict.fromkeys(states))


def _country_statuses(events: list[LegalEvent], as_of: date) -> dict[str, CountryStatus]:
    lapse: dict[str, tuple[date | None, str]] = {}
    reinstated: dict[str, date | None] = {}
    fee: dict[str, tuple[int | None, date | None]] = {}
    for event in events:
        country = event.country
        if not country:
            continue
        # Only what had taken effect by the analysis date counts.
        if event.effective_date and event.effective_date > as_of:
            continue
        if event.code in REINSTATEMENT_CODES:
            current = reinstated.get(country)
            if current is None or (event.effective_date and event.effective_date > current):
                reinstated[country] = event.effective_date
        elif event.code in FEE_CODES:
            year_text = re.sub(r"\D", "", event.fields.get("Year of Fee Payment", ""))
            year = int(year_text) if year_text else None
            paid_on = _yyyymmdd(event.fields.get("Payment DATE")) or event.gazette_date
            previous = fee.get(country)
            if previous is None or (year or 0) > (previous[0] or 0):
                fee[country] = (year, paid_on)
        elif event.influence.strip() == "-":
            reason = event.fields.get("Free Format Text") or event.description
            previous_lapse = lapse.get(country)
            if previous_lapse is None or (
                event.effective_date and (previous_lapse[0] is None or event.effective_date > previous_lapse[0])
            ):
                lapse[country] = (event.effective_date, reason)
    countries = set(lapse) | set(reinstated) | set(fee)
    return {
        c: CountryStatus(
            country=c,
            lapsed_on=lapse.get(c, (None, ""))[0],
            lapse_reason=lapse.get(c, (None, ""))[1],
            reinstated_on=reinstated.get(c),
            last_fee_year=fee.get(c, (None, None))[0],
            last_fee_paid_on=fee.get(c, (None, None))[1],
        )
        for c in sorted(countries)
    }


def assess_ep(
    payload: dict[str, Any],
    *,
    publication_number: str,
    filing_date: date,
    as_of: date,
    data_as_of: str | None = None,
) -> LegalStatusAssessment:
    events = parse_inpadoc(payload)
    expiry = add_years(filing_date, 20)
    term = TermComputation(filing_date, f"EP filing date {filing_date.isoformat()}", 20, 0, expiry)
    countries = _country_statuses(events, as_of)
    designated = designated_states_at_grant(events)
    unitary = any(e.code.startswith(UNITARY_PREFIX) and e.code[1:].isdigit() for e in events)

    evidence = tuple(
        StatusEvidence(
            SOURCE,
            e.code,
            e.description,
            e.effective_date,
            "; ".join(f"{k}: {v}" for k, v in e.fields.items()),
        )
        for e in events
        if e.country or e.influence.strip() == "-" or e.code.startswith(UNITARY_PREFIX) or e.code == "AK"
    )
    reasons: list[str] = []
    unknown_negative = sorted(
        {
            e.code
            for e in events
            if e.influence.strip() == "-"
            and not e.country
            and not (e.effective_date and e.effective_date > as_of)
        }
    )

    def result(status: Status) -> LegalStatusAssessment:
        return LegalStatusAssessment(
            jurisdiction="EP",
            publication_number=publication_number,
            as_of=as_of,
            status=status,
            term=term,
            evidence=evidence,
            review_reasons=tuple(reasons),
            data_as_of=data_as_of,
            countries=tuple(countries.values()),
        )

    if as_of > expiry:
        return result("expired")
    if unknown_negative:
        reasons.append(f"negative EP-level events not mapped to a state: {', '.join(unknown_negative)}")
        return result("undetermined")
    if unitary:
        reasons.append("unitary effect: national lapse events do not cover participating states")
        return result("presumed_in_force")
    if not designated:
        reasons.append("grant-time designated states not found in AK events")
        return result("undetermined")
    alive = [s for s in designated if not (s in countries and countries[s].lapse_in_effect)]
    if not alive:
        return result("lapsed")
    no_evidence = [s for s in alive if s not in countries]
    if no_evidence:
        reasons.append(
            "no national events reported for: " + ", ".join(no_evidence)
            + " (status there is not evidenced either way)"
        )
    return result("presumed_in_force")
