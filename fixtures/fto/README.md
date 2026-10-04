# FTO claim fixtures (public patent publications)

Claims of granted patents, used to test `modules/fto` against real drafting
styles. Public data; no client or case data.

| Directory | Source | Retrieved | Trimming |
|---|---|---|---|
| `us/` | USPTO grant full-text XML (`PTGRXML`), URL from ODP `grantDocumentMetaData.fileLocationURI` | 2026-10-04 | `<claims>…</claims>` element only |
| `ep/` | EPO OPS 3.2 `published-data/publication/docdb/<EP.n.kind>/claims` | 2026-10-04 | unchanged (claims in DE, EN, FR) |

Patents (all from the legal-status coverage set): US 12630442, 10505211,
8623541, 12451529; EP 1819002 B1, 3467934 B1, 2277223 B1. Expected claim
counts and dependencies in the tests were checked by hand against the text.
