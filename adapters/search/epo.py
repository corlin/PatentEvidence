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


class EpoSearchAdapter(BaseSearchAdapter):
    """EPO OPS adapter executing official epo-cli with offline fixture fallback."""

    def __init__(self, cli_path: str | None = None, timeout_seconds: float = 30.0) -> None:
        self.cli_path = cli_path or os.environ.get("PATENT_EVIDENCE_EPO_CLI_PATH") or shutil.which("epo-cli")
        self.timeout_seconds = timeout_seconds
        self.fixtures_path = Path(__file__).resolve().parents[2] / "fixtures" / "connector-responses" / "epo" / "search_sample.json"

    async def search(self, query: str, limit: int = 20) -> list[SearchResultItem]:
        # 1. Try real binary if available and not forced to offline mode
        force_offline = os.environ.get("PATENT_EVIDENCE_USE_OFFLINE_SEARCH", "false").lower() == "true"
        if self.cli_path and not force_offline:
            try:
                cmd = [self.cli_path, "search", "--query", query, "--limit", str(limit), "--json"]
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    data = json.loads(proc.stdout)
                    return self._parse_epo_json(data)
                else:
                    logger.warning("epo-cli failed with code %d: %s; falling back to sandbox fixture", proc.returncode, proc.stderr)
            except Exception as exc:
                logger.warning("epo-cli execution failed: %s; falling back to sandbox fixture", exc)

        # 2. Fallback to offline fixture sandbox
        return self._load_fixture_results(query, limit)

    def _parse_epo_json(self, data: dict[str, Any]) -> list[SearchResultItem]:
        items: list[SearchResultItem] = []
        raw_results = data.get("results") or data.get("patents") or []
        for r in raw_results:
            pub_num = r.get("publication_number") or r.get("doc_number") or "EP0000000A1"
            items.append(
                SearchResultItem(
                    publication_number=pub_num,
                    title=r.get("title") or "European Patent Document",
                    abstract=r.get("abstract") or "No abstract provided in official record.",
                    publication_date=r.get("publication_date"),
                    applicant=r.get("applicant"),
                    ipc_classification=r.get("ipc_classification") or r.get("cpc_classification"),
                    source_type="epo",
                    raw_metadata=r,
                )
            )
        return items

    def _load_fixture_results(self, query: str, limit: int) -> list[SearchResultItem]:
        if not self.fixtures_path.exists():
            return []
        try:
            with open(self.fixtures_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            parsed = self._parse_epo_json(data)
            return parsed[:limit]
        except Exception as exc:
            logger.error("Failed to load EPO fixture: %s", exc)
            return []
