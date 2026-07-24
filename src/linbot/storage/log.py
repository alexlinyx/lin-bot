"""Request logging.

Logging must never break the product: a failed insert is reported to the app
log and swallowed. Losing one corpus row is acceptable; failing a student's
request because the database hiccuped is not.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import async_sessionmaker

from linbot.storage.models import RequestLog

logger = logging.getLogger("linbot.storage")


async def log_request(session_factory: async_sessionmaker, **fields) -> None:
    try:
        async with session_factory() as session:
            session.add(RequestLog(**fields))
            await session.commit()
    except Exception:
        logger.exception("failed to log request (response was already served)")
