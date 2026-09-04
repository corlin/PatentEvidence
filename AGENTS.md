# PatentEvidence contributor guidance

PatentEvidence is an independent commercial repository. Do not import Git
history, credentials, runtime data, databases, cookies, real case files, or
generated artifacts from source repositories.

Keep P0 limited to runnable process and governance scaffolding. Product work
must preserve tenant isolation, provenance, immutable approval boundaries, and
the CNIPR manual-handoff constraint described in the product specification.

Before committing, run the validation commands in `README.md`. Never commit
`.env`, secrets, local runtime data, or the `.superpowers/` workspace.

## Context economy (lean reading)

The working token window is fixed and not to be enlarged. Keep main-thread
context small by default so work is not interrupted by frequent compaction.

- Locate before reading. Use `grep -n` (or `rg`) to find the exact line range
  for a symbol/function/section, then read only that range with `Read`
  `offset`/`limit`.
- Read a whole file only when you genuinely need its full structure. For a
  single method or field, extract it narrowly (e.g. `sed -n 'N,Mp'`) instead
  of dumping the file.
- Prefer isolated `Bash` scans that return a short summary (counts, line
  numbers, one-line findings) over large tool output.
- When a task only needs a fact, fetch that fact; do not load surrounding
  context you will not use.
- On a topic switch, prefer a fresh, narrow investigation over carrying a
  large prior transcript.
