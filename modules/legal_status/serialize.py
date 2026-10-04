"""Extracts, canonical serialization and content hashing for stored assessments (ADR 0006).

Assessments are always computed from the stored ``extract`` (never from the raw
response), so any stored assessment can be reproduced from the database alone.
The extract keeps exactly the fields the rules read and drops personal data;
it is the same trimming that produced ``fixtures/legal-status`` and was
checked to give identical results to the untrimmed responses.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import date
from typing import Any

from modules.legal_status.models import LegalStatusAssessment

# Bump when any rule in us.py / ep.py changes meaning; old assessments stay as recorded.
RULES_VERSION = "legal-status-rules/2"  # /2: reissues are undetermined

_US_META_FIELDS = (
    "filingDate",
    "grantDate",
    "patentNumber",
    "applicationStatusDescriptionText",
    "applicationStatusDate",
    "effectiveFilingDate",
    "applicationTypeCategory",
)
_US_EVENT_PREFIXES = ("M155", "M255", "M355", "EXP", "REM", "DIST", "P574")
_EP_KEEP_CODES = {"AK", "PGFP", "PGRI", "26N", "P01"}
_EP_EVENT_FIELDS = ("@code", "@desc", "@infl", "ops:pre", "ops:L001EP", "ops:L007EP")


def us_extract(record: dict[str, Any]) -> dict[str, Any]:
    meta = record.get("applicationMetaData") or {}
    pta = record.get("patentTermAdjustmentData")
    return {
        "applicationNumberText": record.get("applicationNumberText"),
        "lastIngestionDateTime": record.get("lastIngestionDateTime"),
        "applicationMetaData": {k: meta.get(k) for k in _US_META_FIELDS},
        "eventDataBag": [
            e for e in record.get("eventDataBag") or [] if (e.get("eventCode") or "").startswith(_US_EVENT_PREFIXES)
        ],
        "parentContinuityBag": record.get("parentContinuityBag") or [],
        "patentTermAdjustmentData": (
            {"adjustmentTotalQuantity": pta.get("adjustmentTotalQuantity")} if pta is not None else None
        ),
    }


def _legal_events(node: Any, out: list[dict[str, Any]]) -> None:
    if isinstance(node, dict):
        if "ops:legal" in node:
            items = node["ops:legal"]
            out.extend(items if isinstance(items, list) else [items])
        for value in node.values():
            _legal_events(value, out)
    elif isinstance(node, list):
        for value in node:
            _legal_events(value, out)


def ep_extract(payload: dict[str, Any]) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    _legal_events(payload, events)
    kept = [
        {k: v for k, v in e.items() if k in _EP_EVENT_FIELDS}
        for e in events
        if str(e.get("@code", "")).strip() in _EP_KEEP_CODES
        or str(e.get("@code", "")).strip().startswith("U")
        or str(e.get("@infl", "")).strip() == "-"
    ]
    return {"ops:legal": kept}


def _jsonable(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def assessment_to_dict(assessment: LegalStatusAssessment) -> dict[str, Any]:
    data = _jsonable(asdict(assessment))
    data["rules_version"] = RULES_VERSION
    return data


def canonical_json(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def content_sha256(assessment: LegalStatusAssessment) -> str:
    return hashlib.sha256(canonical_json(assessment_to_dict(assessment)).encode("utf-8")).hexdigest()
