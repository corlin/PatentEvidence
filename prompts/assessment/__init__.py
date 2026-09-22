"""Assessment prompt registry.

Every versioned assessment prompt must be registered here with a stable id
and version string so assessment results can pin which prompt produced them.
"""

from __future__ import annotations

from prompts.assessment.inventive_step import (
    INVENTIVE_STEP_PROMPT_ID,
    INVENTIVE_STEP_PROMPT_VERSION,
    INVENTIVE_STEP_SYSTEM_PROMPT,
    build_inventive_step_user_prompt,
)
from prompts.assessment.novelty import (
    NOVELTY_PROMPT_ID,
    NOVELTY_PROMPT_VERSION,
    NOVELTY_SYSTEM_PROMPT,
    build_novelty_user_prompt,
)
PROMPT_REGISTRY: dict[str, dict[str, str]] = {
    NOVELTY_PROMPT_ID: {
        "version": NOVELTY_PROMPT_VERSION,
        "system_prompt": NOVELTY_SYSTEM_PROMPT,
        "builder": "build_novelty_user_prompt",
    },
    INVENTIVE_STEP_PROMPT_ID: {
        "version": INVENTIVE_STEP_PROMPT_VERSION,
        "system_prompt": INVENTIVE_STEP_SYSTEM_PROMPT,
        "builder": "build_inventive_step_user_prompt",
    },
}

__all__ = [
    "INVENTIVE_STEP_PROMPT_ID",
    "INVENTIVE_STEP_PROMPT_VERSION",
    "INVENTIVE_STEP_SYSTEM_PROMPT",
    "NOVELTY_PROMPT_ID",
    "NOVELTY_PROMPT_VERSION",
    "NOVELTY_SYSTEM_PROMPT",
    "PROMPT_REGISTRY",
    "build_inventive_step_user_prompt",
    "build_novelty_user_prompt",
]
