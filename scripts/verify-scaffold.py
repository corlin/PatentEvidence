#!/usr/bin/env python3
"""Validate required P0 scaffold boundaries and tracked-file hygiene."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


REQUIRED_FILES = (
    "README.md",
    "AGENTS.md",
    ".gitignore",
    ".env.example",
    "LICENSE",
    "pyproject.toml",
    "package.json",
    "pnpm-workspace.yaml",
    "pnpm-lock.yaml",
    "compose.yaml",
    "apps/api/src/patent_evidence_api/main.py",
    "apps/worker/src/patent_evidence_worker/main.py",
    "apps/web/package.json",
    "apps/web/src/App.tsx",
    "ops/docker/api.Dockerfile",
    "ops/docker/worker.Dockerfile",
    "ops/docker/web.Dockerfile",
    "provenance/sources.lock.json",
    "provenance/DERIVATION_POLICY.md",
    "provenance/FILE_MAP.md",
    "provenance/THIRD_PARTY_NOTICES.md",
    "docs/product/mvp-implementation-spec.md",
    "docs/architecture/p0-scaffold.md",
    "docs/operations/local-development.md",
    "docs/operations/source-upgrades.md",
    "scripts/verify-source-lock.py",
    "scripts/verify-scaffold.py",
    ".github/workflows/ci.yml",
)

REQUIRED_DIRECTORIES = (
    "packages/contracts",
    "packages/ui",
    "packages/report-kit",
    "packages/provenance",
    "modules/platform",
    "modules/cases",
    "modules/feature-modeling",
    "modules/retrieval",
    "modules/evidence",
    "modules/assessment",
    "modules/review",
    "modules/delivery",
    "adapters/llm",
    "adapters/epo",
    "adapters/uspto",
    "adapters/cnipr-handoff",
    "adapters/object-storage",
    "adapters/secret-store",
    "db/migrations",
    "db/seeds",
    "db/policies",
    "prompts/feature-extraction",
    "prompts/search-strategy",
    "prompts/evidence-analysis",
    "prompts/assessment",
    "templates/reports/zh-CN-default",
    "templates/reports/agency-custom",
    "fixtures/anonymized-cases",
    "fixtures/connector-responses",
    "fixtures/golden-evidence",
    "tests/unit",
    "tests/contract",
    "tests/integration",
    "tests/security",
    "tests/e2e",
    "tests/release-gates",
    "ops/nginx",
    "ops/backup",
    "ops/monitoring",
    "ops/runbooks",
)


def forbidden_reason(path: str) -> str | None:
    parts = Path(path).parts
    name = Path(path).name
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return "tracked secret/runtime path"
    if name.endswith((".pem", ".key", ".p12", ".pfx")):
        return "tracked secret/runtime path"
    if any(part in {".venv", "node_modules", "__pycache__", ".pytest_cache", "dist", "data", "runtime", "artifacts"} for part in parts):
        return "tracked secret/runtime path"
    if name.endswith((".pyc", ".db", ".sqlite", ".sqlite3")):
        return "tracked secret/runtime path"
    return None


def tracked_paths(root: Path) -> tuple[list[str], str | None]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files"],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        return [], result.stderr.strip() or "not a Git repository"
    return [path for path in result.stdout.splitlines() if path], None


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate PatentEvidence P0 scaffold")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parsed = parser.parse_args(arguments)
    root = parsed.root.resolve()

    errors: list[str] = []
    for relative_path in REQUIRED_FILES:
        if not (root / relative_path).is_file():
            errors.append(f"missing required file: {relative_path}")
    for relative_path in REQUIRED_DIRECTORIES:
        if not (root / relative_path).is_dir():
            errors.append(f"missing required directory: {relative_path}")

    paths, git_error = tracked_paths(root)
    if git_error:
        errors.append(f"cannot inspect tracked files: {git_error}")
    else:
        for path in paths:
            if reason := forbidden_reason(path):
                errors.append(f"{reason}: {path}")

    if errors:
        print("invalid P0 scaffold:", file=sys.stderr)
        print("\n".join(f"- {error}" for error in errors), file=sys.stderr)
        return 1

    print(f"P0 scaffold valid: {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
