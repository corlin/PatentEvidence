# Third-party notices and reuse controls

No third-party code is vendored in P0.

## epo-cli and uspto-cli (MIT)

If either CLI is vendored, distributed, or incorporated into a release, first
fetch the `LICENSE` and copyright notice from the exact locked commit, preserve
the complete MIT license text and notice in that release, record the artifact
hash and retrieval path in `FILE_MAP.md`, and run the relevant adapter contract
tests. P0 permits only a reviewed pinned binary or controlled sidecar; it does
not permit copying either CLI source into the Python services.

## Repositories without a license file

PatentQ, PatentForge, PatentScope, PatentDraw, and cnipr-cli are recorded as
owner-controlled repositories with no license file. Commercial reuse requires a
separate repository-owner authorization record before any code, asset, prompt,
fixture, or documentation is copied. GitHub visibility is not a commercial
reuse license.
