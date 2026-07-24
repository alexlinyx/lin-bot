"""Compare models on live traffic using per-request attribution (ROADMAP §9–§10).

Because every logged row records which model answered, a canary period yields a
directly comparable sample per model. This prints the operational comparison
(volume, latency, fallback and error rates). Quality scoring against the
curated held-out set is stubbed until scoring dimensions are decided
(correctness / helpfulness / tone — some automated, some human or LLM-as-judge).

Usage:
    DATABASE_URL=postgres://... python eval/compare.py [--since 2026-07-01]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from linbot.config import normalize_database_url  # noqa: E402
from linbot.storage.models import RequestLog  # noqa: E402


async def compare(since: datetime | None) -> None:
    engine = create_async_engine(normalize_database_url(os.environ["DATABASE_URL"]))
    query = (
        select(
            func.coalesce(RequestLog.model_id, "(errored before attribution)").label("model"),
            func.count().label("requests"),
            func.avg(RequestLog.latency_ms).label("avg_latency_ms"),
            func.sum(case((RequestLog.fallback_used, 1), else_=0)).label("fallbacks"),
            func.sum(case((RequestLog.error.isnot(None), 1), else_=0)).label("errors"),
        )
        .group_by("model")
        .order_by(func.count().desc())
    )
    if since is not None:
        query = query.where(RequestLog.created_at >= since)

    async with engine.connect() as conn:
        rows = (await conn.execute(query)).all()
    await engine.dispose()

    if not rows:
        print("no logged requests in the selected window")
        return

    header = f"{'model':40} {'requests':>9} {'avg ms':>8} {'fallbacks':>10} {'errors':>7}"
    print(header)
    print("-" * len(header))
    for model, n, avg_ms, fallbacks, errors in rows:
        avg = f"{avg_ms:.0f}" if avg_ms is not None else "-"
        print(f"{model:40} {n:>9} {avg:>8} {fallbacks or 0:>10} {errors or 0:>7}")

    print()
    print("note: held-out quality scoring not yet implemented — this table is the")
    print("operational comparison only. See ROADMAP §10 for the scoring dimensions.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", type=lambda s: datetime.fromisoformat(s), default=None)
    args = parser.parse_args()
    asyncio.run(compare(args.since))
