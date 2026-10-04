#!/usr/bin/env python3
"""Load the US/EP patent corpus from Google Patents Public Data (ADR 0007).

Operator-run, never part of the API or worker images.

  # 1. See exactly what would be scanned (no cost)
  .venv/bin/python scripts/load-patent-corpus.py --as-of 2026-10-04

  # 2. Load, refusing to run if the scan exceeds the cap
  .venv/bin/python scripts/load-patent-corpus.py --as-of 2026-10-04 --max-gb 65 --execute

Requirements: ``uv sync --extra ingest`` (BigQuery client), Google Cloud
Application Default Credentials, ``GOOGLE_CLOUD_PROJECT`` (or ``--project``) for
billing, and ``PATENT_EVIDENCE_WORKER_DATABASE_URL`` for the write.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "apps" / "api" / "src")]

from modules.corpus.query import SOURCE_TABLE, CorpusScope, build_corpus_query, row_to_member  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today(), help="analysis date (YYYY-MM-DD)")
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"), help="billing project")
    parser.add_argument("--max-gb", type=float, help="refuse to execute if the dry-run scan exceeds this")
    parser.add_argument("--execute", action="store_true", help="run the query and write the load")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        from google.cloud import bigquery
    except ImportError:
        print("BigQuery client missing: run `uv sync --extra ingest`", file=sys.stderr)
        return 2
    if not args.project:
        print("set GOOGLE_CLOUD_PROJECT or pass --project (billing project)", file=sys.stderr)
        return 2

    scope = CorpusScope(as_of=args.as_of)
    sql = build_corpus_query(scope)
    client = bigquery.Client(project=args.project)
    dry = client.query(sql, job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False))
    scan_gb = dry.total_bytes_processed / 1e9
    print(f"scope: {scope.as_record()}")
    print(f"dry-run scan: {scan_gb:.2f} GB")
    if not args.execute:
        print("dry run only; add --execute and --max-gb to load")
        return 0
    if args.max_gb is None:
        print("--execute requires --max-gb", file=sys.stderr)
        return 2
    if scan_gb > args.max_gb:
        print(f"refusing: {scan_gb:.2f} GB exceeds --max-gb {args.max_gb}", file=sys.stderr)
        return 1

    started_at = datetime.now(UTC)
    source_modified = client.get_table(SOURCE_TABLE).modified
    job = client.query(sql, job_config=bigquery.QueryJobConfig(maximum_bytes_billed=int(args.max_gb * 1e9)))
    members = [row_to_member(dict(row)) for row in job.result()]
    finished_at = datetime.now(UTC)

    load_id, count = asyncio.run(_write(scope, sql, members, started_at, finished_at, job.total_bytes_billed, source_modified))
    by_kind = collections.Counter((m["jurisdiction"], m["kind"]) for m in members)
    by_match = collections.Counter(m["scope_match"] for m in members)
    print(f"load {load_id}: {count} members, billed {(job.total_bytes_billed or 0) / 1e9:.2f} GB")
    print(f"source table last modified: {source_modified.isoformat() if source_modified else 'unknown'}")
    print(f"by jurisdiction/kind: {dict(sorted(by_kind.items()))}")
    print(f"by classification match: {dict(by_match)}")
    return 0


async def _write(scope, sql, members, started_at, finished_at, bytes_billed, source_modified):
    from modules.corpus.store import record_load
    from patent_evidence_api.core.database import create_engine, create_worker_session_factory
    from patent_evidence_api.core.settings import Settings

    engine = create_engine(Settings().worker_database_url)
    try:
        async with create_worker_session_factory(engine)() as session, session.begin():
            return await record_load(
                session,
                scope=scope,
                sql=sql,
                members=members,
                started_at=started_at,
                finished_at=finished_at,
                bytes_billed=bytes_billed,
                source_table_modified_at=source_modified,
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
