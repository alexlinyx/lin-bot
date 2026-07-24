"""Build a held-out evaluation set from logged production questions (ROADMAP §10).

Samples real student questions from the `requests` table into a JSONL file.
Reference answers start empty — filling them in (by hand, or reviewed model
output) is the curation step that makes the set ground truth. Once curated,
every candidate model is scored against this file *before* it sees live traffic.

Usage:
    DATABASE_URL=postgres://... python eval/build_eval_set.py --limit 100 --out eval/heldout.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from linbot.config import normalize_database_url  # noqa: E402
from linbot.storage.models import RequestLog  # noqa: E402


async def build(limit: int, out_path: str) -> int:
    engine = create_async_engine(normalize_database_url(os.environ["DATABASE_URL"]))
    # Distinct questions from successful requests, randomly sampled so the set
    # reflects the real traffic distribution rather than the newest topics.
    query = (
        select(RequestLog.question, func.max(RequestLog.model_id))
        .where(RequestLog.error.is_(None))
        .group_by(RequestLog.question)
        .order_by(func.random())
        .limit(limit)
    )
    async with engine.connect() as conn:
        rows = (await conn.execute(query)).all()
    await engine.dispose()

    with open(out_path, "w") as f:
        for question, model_id in rows:
            f.write(
                json.dumps(
                    {"question": question, "reference_answer": None, "source_model": model_id}
                )
                + "\n"
            )
    return len(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--out", default="eval/heldout.jsonl")
    args = parser.parse_args()
    n = asyncio.run(build(args.limit, args.out))
    print(f"wrote {n} questions to {args.out} (reference answers need curation)")
