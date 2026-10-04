# Legal-status fixtures (public patent-office records)

These are **public** legal-status records of published, granted patents. They contain no
client or case data. They test `modules/legal_status` against real source behaviour rather
than invented payloads.

| Directory | Source | Retrieved |
|---|---|---|
| `us/` | USPTO Open Data Portal, `GET /api/v1/patent/applications/search?q=applicationMetaData.patentNumber:<n>` → `patentFileWrapperDataBag[0]` | 2026-10-04 |
| `ep/` | EPO OPS 3.2 INPADOC, `GET /rest-services/legal/publication/docdb/EP.<n>.<kind>` | 2026-10-04 |

The patents were picked by hash from in-scope (H01M) US/EP grants, one per rule the tests
cover (see the 2026-10-04 data feasibility spike and ADR 0005).

Trimming (so fixtures hold only what the rules read, and no personal data):

- **US:** `applicationNumberText`, `lastIngestionDateTime`; selected `applicationMetaData`
  fields (filing/grant dates, patent number, status text and date); `eventDataBag` filtered to
  maintenance-fee, expiry, reminder and terminal-disclaimer events (`M155*`, `M255*`, `M355*`,
  `EXP*`, `REM*`, `DIST`, `P574`); `parentContinuityBag`; `patentTermAdjustmentData.adjustmentTotalQuantity`.
  Inventor, attorney and correspondence data are not included.
- **EP:** INPADOC events limited to `AK`, `PGFP`, `PGRI`, `26N`, `P01`, unitary `U*` and every event
  with negative influence (`@infl` = `-`); fields `@code`, `@desc`, `@infl`, `ops:pre`,
  `ops:L001EP`, `ops:L007EP`. Inventor and party-data events are dropped.

The trimming was checked to give the same assessment as the untrimmed responses.
Because the sources change over time, a fresh download may differ from these snapshots.
