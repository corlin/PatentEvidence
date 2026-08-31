# Derivation policy

`provenance/sources.lock.json` is the authoritative inventory of external
source repositories for this product. It does not make any source repository a
runtime dependency and does not grant reuse rights.

Before adding a derivative file, obtain the required owner authorization,
record the source path and immutable commit in `FILE_MAP.md`, describe the
modification, and add focused contract coverage. Substantial copied material
must carry a `Derived from <repo>/<path>@<commit>` header.

Never copy `.env` files, credentials, cookies, databases, customer data,
generated artifacts, or source Git history. EPO and USPTO integrations may use
only a reviewed pinned binary or sidecar. CNIPR is manual-handoff-only: no
direct HTTP, headless service, cookie replay, bulk collection, or persistent
session is permitted.
