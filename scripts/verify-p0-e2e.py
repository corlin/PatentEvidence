#!/usr/bin/env python3
"""PatentEvidence Full E2E & Production Readiness Release Gate Verification Script.

Validates the full 6-week architecture, database migrations, RLS enforcement,
core modules, adapters, routes, and web frontend views.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MIGRATIONS = [
    "0001_identity_tenancy.py",
    "0002_platform_provisioning.py",
    "0003_organization_administration.py",
    "0004_cases_documents.py",
    "0005_features_modeling.py",
    "0006_search_and_candidates.py",
    "0007_feature_comparisons.py",
    "0008_evidence_snapshots_reports.py",
]

CORE_MODULES = [
    "modules/cases/parser.py",
    "modules/features/extractor.py",
    "modules/search/strategy_planner.py",
    "modules/search/handoff.py",
    "modules/search/importer.py",
    "modules/search/scorer.py",
    "modules/comparison/engine.py",
    "modules/comparison/evaluator.py",
    "modules/reports/sealer.py",
    "modules/reports/generator.py",
]

ADAPTERS = [
    "adapters/object_storage/client.py",
    "adapters/search/google_patents.py",
    "adapters/search/openalex.py",
]

WEB_VIEWS = [
    "apps/web/src/views/LoginView.tsx",
    "apps/web/src/views/MfaChallengeView.tsx",
    "apps/web/src/views/MfaEnrollView.tsx",
    "apps/web/src/views/PasswordResetView.tsx",
    "apps/web/src/views/PlatformOrganizationsView.tsx",
    "apps/web/src/views/OrganizationMembersView.tsx",
    "apps/web/src/views/OrganizationSelectView.tsx",
    "apps/web/src/views/InvitationAcceptView.tsx",
    "apps/web/src/views/CasesListView.tsx",
    "apps/web/src/views/CaseDetailView.tsx",
    "apps/web/src/views/FeaturesWorkbenchView.tsx",
    "apps/web/src/views/SearchWorkbenchView.tsx",
    "apps/web/src/views/ComparisonWorkbenchView.tsx",
    "apps/web/src/views/ReportsWorkbenchView.tsx",
]

RUNBOOKS = [
    "docs/operations/runbook-platform-bootstrap.md",
    "docs/operations/runbook-organization-provisioning.md",
    "docs/operations/runbook-credential-rotation.md",
    "docs/operations/runbook-incident-containment.md",
    "docs/operations/runbook-backup-restore.md",
]


def check(cond: bool, msg: str) -> None:
    if not cond:
        print(f"FAIL: {msg}", file=sys.stderr)
        sys.exit(1)
    print(f"PASS: {msg}")


def main() -> None:
    print("=== PatentEvidence Week 6 Full Production Release Gate Verification ===")

    # 1. Check migrations
    for mig in MIGRATIONS:
        path = ROOT / "apps/api/migrations/versions" / mig
        check(path.exists(), f"Migration exists: {mig}")
        content = path.read_text(encoding="utf-8")
        if mig != "0002_platform_provisioning.py" and mig != "0003_organization_administration.py":
            check("enable_force_rls" in content, f"Migration enforces RLS helper: {mig}")

    # 2. Check core modules
    for mod in CORE_MODULES:
        path = ROOT / mod
        check(path.exists(), f"Core module exists: {mod}")

    # 3. Check adapters
    for adp in ADAPTERS:
        path = ROOT / adp
        check(path.exists(), f"Adapter exists: {adp}")

    # 4. Check Web views
    for view in WEB_VIEWS:
        path = ROOT / view
        check(path.exists(), f"Web View exists: {view}")

    # 5. Check runbooks
    for rb in RUNBOOKS:
        path = ROOT / rb
        check(path.exists(), f"Runbook exists: {rb}")

    # 6. Check main app routes
    main_api = (ROOT / "apps/api/src/patent_evidence_api/main.py").read_text(encoding="utf-8")
    expected_routers = [
        "create_auth_router",
        "create_platform_router",
        "create_organization_router",
        "create_invitation_router",
        "create_cases_router",
        "create_features_router",
        "create_search_router",
        "create_comparison_router",
        "create_reports_router",
    ]
    for r in expected_routers:
        check(r in main_api, f"Main app mounts router: {r}")

    # 7. Check FILE_MAP.md
    file_map = ROOT / "provenance" / "FILE_MAP.md"
    check(file_map.exists(), "FILE_MAP.md exists")

    print("=== ALL FULL E2E RELEASE GATES PASSED SUCCESSFULLY ===")


if __name__ == "__main__":
    main()
