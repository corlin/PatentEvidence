#!/usr/bin/env python3
"""Validate the immutable PatentEvidence source-lock contract."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from typing import Any


COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")

# The approved P0 source inventory is intentionally explicit so a review can
# compare each immutable source identity without decoding a derived digest.
APPROVED_SOURCES = {
    "PatentQ": {
        "repository": "https://github.com/corlin/PatentQ.git",
        "commit": "eb63654464e51fa0d68027679c6626fb2a0c608b",
    },
    "PatentForge": {
        "repository": "https://github.com/corlin/PatentForge.git",
        "commit": "7b6067a9a57019c1a59831de7841bd71c7bda433",
    },
    "PatentScope": {
        "repository": "https://github.com/corlin/PatentScope.git",
        "commit": "323ed05b6a148c012e0e163de69c927d7b639a37",
    },
    "PatentDraw": {
        "repository": "https://github.com/corlin/PatentDraw.git",
        "commit": "6a0801f43be962476e9aa276b9b32c6c37677b95",
    },
    "epo-cli": {
        "repository": "https://github.com/corlin/epo-cli.git",
        "commit": "07491e42e6db37871cb51ffe55c84712ea053d69",
    },
    "uspto-cli": {
        "repository": "https://github.com/corlin/uspto-cli.git",
        "commit": "be955e3ce0cb484a8fed6fa65cd23a33b0ed99f0",
    },
    "cnipr-cli": {
        "repository": "https://github.com/corlin/cnipr-cli.git",
        "commit": "46d4fbc2b1294bd2ebfb23ffd5046bfb6a13e0de",
    },
}


def is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_lock(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["lockfile root must be an object"]
    if payload.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if payload.get("product") != "PatentEvidence":
        errors.append("product must be PatentEvidence")

    sources = payload.get("sources")
    if not isinstance(sources, list) or len(sources) != len(APPROVED_SOURCES):
        return [*errors, "sources must contain exactly seven records"]

    names: list[str] = []
    repositories: list[str] = []
    for index, source in enumerate(sources, start=1):
        if not isinstance(source, dict):
            errors.append(f"source {index} must be an object")
            continue
        name = source.get("name")
        repository = source.get("repository")
        commit = source.get("commit")
        if not is_non_empty_string(name):
            errors.append(f"source {index} must have a non-empty name")
        else:
            names.append(name)
        if not is_non_empty_string(repository):
            errors.append(f"source {index} must have a non-empty repository")
        else:
            repositories.append(repository)
        if not isinstance(commit, str) or not COMMIT_PATTERN.fullmatch(commit):
            errors.append(f"source {index} commit must be 40 lowercase hexadecimal characters")
        if not is_non_empty_string(source.get("license_status")):
            errors.append(f"source {index} license_status must be a non-empty string")
        if not is_non_empty_string(source.get("integration")):
            errors.append(f"source {index} integration must be a non-empty string")
        scope = source.get("scope")
        if not isinstance(scope, list) or not scope or not all(is_non_empty_string(item) for item in scope):
            errors.append(f"source {index} scope must be a non-empty list of non-empty strings")

        approved_source = APPROVED_SOURCES.get(name) if is_non_empty_string(name) else None
        if approved_source is None:
            errors.append(f"source {index} name is not an approved source")
        else:
            if repository != approved_source["repository"]:
                errors.append(f"source {index} repository does not match approved source lock")
            if commit != approved_source["commit"]:
                errors.append(f"source {index} commit does not match approved source lock")

    if len(names) != len(set(names)):
        errors.append("source names must be unique")
    if len(repositories) != len(set(repositories)):
        errors.append("source repositories must be unique")
    if set(names) != set(APPROVED_SOURCES):
        errors.append("source names must exactly match the approved source lock")
    return errors


def main(arguments: list[str] | None = None) -> int:
    default_lock = Path(__file__).resolve().parents[1] / "provenance" / "sources.lock.json"
    lock_path = Path((arguments or sys.argv[1:])[0]) if (arguments or sys.argv[1:]) else default_lock
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"invalid source lock: {error}", file=sys.stderr)
        return 1

    errors = validate_lock(payload)
    if errors:
        print("invalid source lock:", file=sys.stderr)
        print("\n".join(f"- {error}" for error in errors), file=sys.stderr)
        return 1

    print(f"source lock valid: {lock_path} (7 unique sources)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
