# Assessment module boundary

Deterministic pre-assessment rules and combination-motivation screening
(spec 6.6). Judgment vocabulary mirrors the comparison stage:
`identical | equivalent | different | insufficient_evidence`.

- `rules.py` — application-controlled gates, version-pinned
  (`assessment-rules-v3`):
  - priority verification (`verify_priority`): 多项优先权取最早有效项、
    部分优先权按特征回落申请日、期限（发明/实用新型 12 个月、外观设计 6 个月）、
    首次申请、相同主题、证明是否核验；不成立的优先权使基准日回落到申请日。
  - reference date gate (现有技术 / 抵触申请 / 不可用 / 日期未知)，按特征逐项
    判断，文献级取最保守结果。
  - novelty single-reference/all-elements gate, combination coverage
    screening (抵触申请 excluded), evidence-completeness finding, the
    `ThreeStepScaffold` for inventive-step steps 1–2, the human-filled
    `MotivationChecklist` for step 3 (completeness validation only),
    auxiliary factors with evidence requirements, a hindsight smell check, and
    `assess_evidence_completeness` (来源覆盖率 / 引证定位 / 引用逐字核验 /
    数据源失败 / 法律状态时点), and entity-level novelty observations
    (`entity_level_observations`: 数值范围重叠 / 上位下位概括 / 惯用手段置换).
    No model calls, no vendor integration.

Evidence completeness distinguishes blocking gaps from flags: 引证未定位、
引用未逐字核验、数据源失败 are blocking (禁止输出结论); 摘要级引用、
数据源部分成功、缺失法律状态时点 are flags that require human judgement.

- `package.py` — `assess_case()` runs every gate once and returns an
  `AssessmentPackage` (priority verification, findings, three-step scaffold,
  step-3 checklist state, evidence completeness, blockers, flags, rules
  version, prompt versions, and `requires_human_confirmation`). It is the
  single entry point a future API layer should call; it still emits no
  patentability conclusion.

Priority is upstream of the date gate: a wrong reference date invalidates every
downstream novelty and inventive-step judgment, so invalid or unverified
priority claims surface as `priority_verification` findings rather than being
silently absorbed into a single date.

### Entity-level observations never change a judgment

`entity_level_observations` produces `EntityLevelObservation` candidates with
`effect = may_defeat_novelty | does_not_defeat_novelty | undetermined`, and
`requires_human_confirmation` is always True. They are computed *after* the
gates and never write back into the comparison cells, so they can neither
upgrade a `different` cell to `identical` nor trigger the single-reference
novelty gate. Numerical range overlap stays a candidate precisely because 选择发明
and 实施例点值 are exceptions only a human can confirm; an undocumented
substitute is never presumed to be a 惯用手段.

- `records.py` — freezes a package into an append-only
  `AssessmentVersionRecord`: rules version, prompt versions, the full payload
  and a SHA-256 over the canonicalised payload, so an approval or report can
  bind to a byte-stable snapshot instead of to whatever the rules produce
  today. There is no update path; a revision is a new version number.

Nothing here emits a patentability conclusion: outputs are candidate findings
that a patent agent must confirm and a reviewer must approve.
