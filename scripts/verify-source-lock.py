#!/usr/bin/env python3
"""Validate the immutable PatentEvidence source-lock contract."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from typing import Any


COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def validate_lock(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["lockfile root must be an object"]
    if payload.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if payload.get("product") != "PatentEvidence":
        errors.append("product must be PatentEvidence")

    sources = payload.get("sources")
    if not isinstance(sources, list) or len(sources) != 7:
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
        if not isinstance(name, str) or not name:
            errors.append(f"source {index} must have a non-empty name")
        else:
            names.append(name)
        if not isinstance(repository, str) or not repository:
            errors.append(f"source {index} must have a non-empty repository")
        else:
            repositories.append(repository)
        if not isinstance(commit, str) or not COMMIT_PATTERN.fullmatch(commit):
            errors.append(f"source {index} commit must be 40 lowercase hexadecimal characters")

    if len(names) != len(set(names)):
        errors.append("source names must be unique")
    if len(repositories) != len(set(repositories)):
        errors.append("source repositories must be unique")
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
