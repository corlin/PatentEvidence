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
  auxiliary factors with evidence requirements, a hindsight smell check, and
  `assess_evidence_completeness` (来源覆盖率 / 引证定位 / 引用逐字核验 /
  数据源失败 / 法律状态时点). No model calls, no vendor integration.

Evidence completeness distinguishes blocking gaps from flags: 引证未定位、
引用未逐字核验、数据源失败 are blocking (禁止输出结论); 摘要级引用、
数据源部分成功、缺失法律状态时点 are flags that require human judgement.

- `package.py` — `assess_case()` runs every gate once and returns an
  `AssessmentPackage` (findings, three-step scaffold, step-3 checklist state,
  evidence completeness, blockers, flags, rules version, prompt versions, and
  `requires_human_confirmation`). It is the single entry point a future API
  layer should call; it still emits no patentability conclusion.

Nothing here emits a patentability conclusion: outputs are candidate findings
that a patent agent must confirm and a reviewer must approve.
