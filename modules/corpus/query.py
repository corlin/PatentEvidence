"""US/EP patent corpus: scope, BigQuery query and row normalization (ADR 0007).

Pure functions only, so the exact query that defines a corpus load can be
tested, hashed and recorded with the load.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from modules.legal_status.us import add_years

SOURCE_TABLE = "patents-public-data.patents.publications"


@dataclass(frozen=True)
class CorpusScope:
    as_of: date
    classification_prefixes: tuple[str, ...] = ("H01M", "H02J")
    us_kinds: tuple[str, ...] = ("B1", "B2", "E1")
    ep_kinds: tuple[str, ...] = ("B1", "B2", "B3")
    statutory_years: int = 20
    # US: patent term adjustment can extend the term (measured up to 1,220 days);
    # EP: no term adjustment under the EPC. See ADR 0007 for the calibration rule.
    us_margin_years: int = 5
    ep_margin_years: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def cutoff(self, jurisdiction: str) -> date:
        margin = self.us_margin_years if jurisdiction == "US" else self.ep_margin_years
        return add_years(self.as_of, -(self.statutory_years + margin))

    def as_record(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "classification_prefixes": list(self.classification_prefixes),
            "us_kinds": list(self.us_kinds),
            "ep_kinds": list(self.ep_kinds),
            "statutory_years": self.statutory_years,
            "us_margin_years": self.us_margin_years,
            "ep_margin_years": self.ep_margin_years,
            "us_filing_date_cutoff": self.cutoff("US").isoformat(),
            "ep_filing_date_cutoff": self.cutoff("EP").isoformat(),
        }


def _yyyymmdd(day: date) -> int:
    return day.year * 10000 + day.month * 100 + day.day


def _quoted(values: tuple[str, ...]) -> str:
    for value in values:
        if not value.isalnum():
            raise ValueError(f"unsafe literal in corpus scope: {value!r}")
    return ", ".join(f"'{v}'" for v in values)


def build_corpus_query(scope: CorpusScope) -> str:
    """Deterministic SQL for one corpus load (literals validated; no user input)."""
    prefix_match = lambda column: " OR ".join(  # noqa: E731
        f"STARTS_WITH({column}.code, '{p}')" for p in scope.classification_prefixes
    )
    _quoted(scope.classification_prefixes)
    return f"""SELECT
  p.publication_number,
  p.country_code,
  p.kind_code,
  p.application_number,
  p.family_id,
  p.filing_date,
  p.grant_date,
  p.priority_date,
  ARRAY(SELECT DISTINCT c.code FROM UNNEST(p.cpc) c ORDER BY c.code) AS cpc_codes,
  ARRAY(SELECT DISTINCT i.code FROM UNNEST(p.ipc) i ORDER BY i.code) AS ipc_codes,
  p.assignee AS assignees_original,
  ARRAY(SELECT a.name FROM UNNEST(p.assignee_harmonized) a) AS assignees_harmonized,
  (SELECT t.text FROM UNNEST(p.title_localized) t WHERE t.language = 'en' LIMIT 1) AS title_en,
  (SELECT t.text FROM UNNEST(p.title_localized) t WHERE t.language != 'en' LIMIT 1) AS title_original,
  EXISTS (SELECT 1 FROM UNNEST(p.cpc) c WHERE {prefix_match('c')}) AS cpc_match,
  EXISTS (SELECT 1 FROM UNNEST(p.ipc) i WHERE {prefix_match('i')}) AS ipc_match
FROM `{SOURCE_TABLE}` p
WHERE p.grant_date > 0
  AND (
    (p.country_code = 'US' AND p.kind_code IN ({_quoted(scope.us_kinds)})
     AND p.filing_date >= {_yyyymmdd(scope.cutoff("US"))})
    OR
    (p.country_code = 'EP' AND p.kind_code IN ({_quoted(scope.ep_kinds)})
     AND p.filing_date >= {_yyyymmdd(scope.cutoff("EP"))})
  )
  AND (
    EXISTS (SELECT 1 FROM UNNEST(p.cpc) c WHERE {prefix_match('c')})
    OR EXISTS (SELECT 1 FROM UNNEST(p.ipc) i WHERE {prefix_match('i')})
  )
ORDER BY p.publication_number"""


def query_sha256(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def _date(value: Any) -> date | None:
    """BigQuery stores dates as YYYYMMDD integers; 0 means unknown."""
    if not value:
        return None
    number = int(value)
    try:
        return date(number // 10000, number // 100 % 100, number % 100)
    except ValueError:
        return None


def row_to_member(row: dict[str, Any]) -> dict[str, Any]:
    cpc, ipc = bool(row.get("cpc_match")), bool(row.get("ipc_match"))
    if not (cpc or ipc):
        raise ValueError(f"row outside classification scope: {row.get('publication_number')}")
    return {
        "publication_number": row["publication_number"],
        "jurisdiction": row["country_code"],
        "kind": row["kind_code"],
        # Google's application number; NOT the USPTO application number. Grouping only.
        "application_number": row.get("application_number"),
        "family_id": row.get("family_id") or None,
        "filing_date": _date(row.get("filing_date")),
        "grant_date": _date(row.get("grant_date")),
        "priority_date": _date(row.get("priority_date")),
        "cpc_codes": list(row.get("cpc_codes") or []),
        "ipc_codes": list(row.get("ipc_codes") or []),
        "assignees_original": list(row.get("assignees_original") or []),
        "assignees_harmonized": list(row.get("assignees_harmonized") or []),
        "title_en": row.get("title_en"),
        "title_original": row.get("title_original"),
        "scope_match": "both" if cpc and ipc else ("cpc" if cpc else "ipc"),
    }
