# Source upgrade procedure

Source upgrades are reviewed governance changes, not routine dependency bumps.

1. Obtain authorization where the locked repository has no applicable license.
2. Update exactly one or more reviewed immutable commits in `sources.lock.json`.
3. Inspect the upstream changes and update the affected adapter or contract.
4. Update `FILE_MAP.md`, notices, and relevant fixtures.
5. Run source-lock validation and affected contract tests before review.

Do not replace a lock with a branch name, `latest` tag, or unverified download
URL. EPO and USPTO stay pinned-binary/sidecar integrations. CNIPR must retain
the manual-handoff-only constraints.
