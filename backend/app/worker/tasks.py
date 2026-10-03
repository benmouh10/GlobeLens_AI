"""
GlobeLens AI — Celery tasks.

Tasks are synchronous entry points (Celery's model) that drive async services by
creating their own database session. They must not reuse a request-scoped
session: a worker process has no FastAPI request.
"""
import asyncio
import logging

from app.core.database import AsyncSessionFactory
from app.services.newsletter_service import send_digest
from app.services.push_service import send_daily_briefings
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.worker.tasks.send_digest_task")
def send_digest_task(frequency: str = "daily") -> dict:
    """Send the digest for a cadence; scheduled by beat, also runnable ad hoc."""

    async def _run() -> dict:
        async with AsyncSessionFactory() as db:
            return await send_digest(db, frequency)

    result = asyncio.run(_run())
    logger.info("Digest task finished: %s", result)
    return result


@celery_app.task(name="app.worker.tasks.send_push_briefings_task")
def send_push_briefings_task() -> dict:
    """Send the daily Web Push briefing to opted-in users (scheduled by beat)."""

    async def _run() -> dict:
        async with AsyncSessionFactory() as db:
            return await send_daily_briefings(db)

    result = asyncio.run(_run())
    logger.info("Push briefing task finished: %s", result)
    return result
