from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from adapters.search.base import BaseSearchAdapter, SearchResultItem

logger = logging.getLogger(__name__)


class UsptoSearchAdapter(BaseSearchAdapter):
    """USPTO PatentsView / Dossier adapter executing official uspto-cli with sandbox fallback."""

    def __init__(
        self,
        cli_path: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.cli_path = cli_path or os.environ.get("PATENT_EVIDENCE_USPTO_CLI_PATH") or shutil.which("uspto-cli")
        self.api_key = api_key or os.environ.get("PATENT_EVIDENCE_USPTO_API_KEY")
        self.timeout_seconds = timeout_seconds
        self.fixtures_path = Path(__file__).resolve().parents[2] / "fixtures" / "connector-responses" / "uspto" / "search_sample.json"

    async def search(self, query: str, limit: int = 20) -> list[SearchResultItem]:
        # 1. Try real binary if available and not forced to offline mode
        force_offline = os.environ.get("PATENT_EVIDENCE_USE_OFFLINE_SEARCH", "false").lower() == "true"
        if self.cli_path and not force_offline:
            try:
                cmd = [self.cli_path, "search", "--query", query, "--limit", str(limit), "--json"]
                env = os.environ.copy()
                if self.api_key:
                    env["USPTO_API_KEY"] = self.api_key
                proc = subprocess.run(
                    cmd,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    data = json.loads(proc.stdout)
                    return self._parse_uspto_json(data)
                else:
                    logger.warning("uspto-cli failed with code %d: %s; falling back to sandbox fixture", proc.returncode, proc.stderr)
            except Exception as exc:
                logger.warning("uspto-cli execution failed: %s; falling back to sandbox fixture", exc)

        # 2. Fallback to offline fixture sandbox
        return self._load_fixture_results(query, limit)

    def _parse_uspto_json(self, data: dict[str, Any]) -> list[SearchResultItem]:
        items: list[SearchResultItem] = []
        raw_patents = data.get("patents") or data.get("results") or []
        for p in raw_patents:
            num = p.get("patent_number") or p.get("publication_number") or "US0000000B2"
            items.append(
                SearchResultItem(
                    publication_number=num,
                    title=p.get("patent_title") or p.get("title") or "US Patent Document",
                    abstract=p.get("patent_abstract") or p.get("abstract") or "No abstract provided in official record.",
                    publication_date=p.get("patent_date") or p.get("publication_date"),
                    applicant=p.get("assignee_organization") or p.get("applicant"),
                    ipc_classification=p.get("ipc_classification") or p.get("cpc_classification"),
                    source_type="uspto",
                    raw_metadata=p,
                )
            )
        return items

    def _load_fixture_results(self, query: str, limit: int) -> list[SearchResultItem]:
        if not self.fixtures_path.exists():
            return []
        try:
            with open(self.fixtures_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            parsed = self._parse_uspto_json(data)
            return parsed[:limit]
        except Exception as exc:
            logger.error("Failed to load USPTO fixture: %s", exc)
            return []
