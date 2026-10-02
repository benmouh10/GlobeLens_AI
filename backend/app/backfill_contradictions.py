"""
One-off: scan existing multi-source events for cross-source contradictions.

    python -m app.backfill_contradictions --plan
    python -m app.backfill_contradictions
"""
import argparse
import asyncio

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionFactory
from app.entities.models import Article, Event
from app.services.cache_service import cache_service
from app.services.contradiction_service import scan_event_contradictions


async def main(plan_only: bool) -> None:
    async with AsyncSessionFactory() as session:
        total = (await session.execute(select(func.count()).select_from(Event))).scalar()

        events = (
            await session.execute(
                select(Event)
                .options(selectinload(Event.articles).selectinload(Article.source))
                .where(Event.summary.isnot(None))
            )
        ).scalars().all()

        # A single outlet cannot contradict itself, so those events are not
        # worth scanning or reporting as "0 contradictions".
        multi = []
        for e in events:
            bodies = [a for a in e.articles if a.content and a.content.strip()]
            sources = {a.source_id for a in bodies if a.source_id}
            if len(sources) >= 2:
                multi.append((e, len(bodies), len(sources)))

        print(f"events: {total}")
        print(f"single-source (cannot contradict): {total - len(multi)}")
        print(f"multi-source (scannable): {len(multi)}")

        if plan_only:
            print("\nplan only; nothing changed.")
            return

    flagged = 0
    stored = 0
    for event, n_articles, n_sources in multi:
        async with AsyncSessionFactory() as session:
            try:
                count = await scan_event_contradictions(event.id, session)
                await session.commit()
            except Exception as exc:  # noqa: BLE001 - report, keep going
                await session.rollback()
                print(f"  {str(event.id)[:8]} failed: {exc}")
                continue
            stored += count
            flagged += 1 if count else 0
            marker = f"  <-- {count} contradiction(s)" if count else ""
            print(
                f"  {str(event.id)[:8]} sources={n_sources} "
                f"articles={n_articles} contradictions={count}{marker}"
            )

    print(f"\nevents with contradictions: {flagged}/{len(multi)}")
    print(f"total contradictions stored: {stored}")

    # The embedding cache holds a Redis connection. Without an explicit close
    # its __del__ runs after the loop is gone and dumps a spurious
    # "Event loop is closed" traceback at the end of every run.
    await cache_service.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.plan))