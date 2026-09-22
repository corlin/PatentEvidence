# Assessment module boundary

Deterministic pre-assessment rules and combination-motivation screening
(spec 6.6). Judgment vocabulary mirrors the comparison stage:
`identical | equivalent | different | insufficient_evidence`.

- `rules.py` — application-controlled gates, version-pinned
  (`assessment-rules-v2`): reference date gate (现有技术 / 抵触申请 / 不可用 /
  日期未知), novelty single-reference/all-elements gate, combination coverage
  screening (抵触申请 excluded), evidence-completeness finding, the
  `ThreeStepScaffold` for inventive-step steps 1–2, the human-filled
  `MotivationChecklist` for step 3 (completeness validation only),
  auxiliary factors with evidence requirements, and a hindsight smell check.
  No model calls, no vendor integration.

Nothing here emits a patentability conclusion: outputs are candidate findings
that a patent agent must confirm and a reviewer must approve.
