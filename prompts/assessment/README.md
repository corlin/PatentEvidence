# Assessment prompts

Versioned, reviewed prompts for the pre-assessment stage (spec 6.6). Each
prompt lives in its own module with a stable `*_PROMPT_ID` and
`*_PROMPT_VERSION` and is registered in `__init__.py` (`PROMPT_REGISTRY`) so
assessment results can pin the prompt that produced them.

| id | version | scope |
| --- | --- | --- |
| `assessment/novelty` | `novelty-v1` | Novelty single-reference reasoning; supports (never overrides) the deterministic single-reference/all-elements gate in `modules/assessment/rules.py` |
| `assessment/inventive_step` | `inventive-step-v1` | Three-step inventiveness sequence with anti-hindsight constraints; consumes `ThreeStepScaffold` |
| `assessment/originality` | `originality-v1` | Copyright originality (独立完成 + 最低限度创造性), idea/expression dichotomy, merger/limited-expression filtering |

Rules of this boundary:

- Prompts are reviewed artifacts: changing prompt text requires bumping the
  version string and updating this README.
- Prompt output is candidate reasoning only; every conclusion must cite
  verifiable source locations or be marked `insufficient_evidence`.
- Deterministic gates (novelty single-reference, combination coverage,
  evidence completeness) stay in `modules/assessment/rules.py`; prompts and
  Jev signals may enrich reasoning but cannot bypass a gate.
