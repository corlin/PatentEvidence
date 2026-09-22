# Assessment module boundary

Deterministic pre-assessment rules and combination-motivation screening
(spec 6.6). Judgment vocabulary mirrors the comparison stage:
`identical | equivalent | different | insufficient_evidence`.

- `rules.py` — application-controlled gates, version-pinned
  (`assessment-rules-v1`): novelty single-reference/all-elements gate,
  combination coverage screening, evidence-completeness finding, and the
  `ThreeStepScaffold` for inventive-step steps 1–2. No model calls, no vendor
  integration.

Nothing here emits a patentability conclusion: outputs are candidate findings
that a patent agent must confirm and a reviewer must approve.
