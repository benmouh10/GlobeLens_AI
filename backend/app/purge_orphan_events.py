"""
One-off: delete events that no longer have any articles.

The purge of three CNN app-download stubs removed the only article on three
events, leaving event rows with zero articles and summaries describing the
interstitial rather than any news. They cannot be enriched (nothing to read)
and they cannot be mapped, so they only distort counts.

    python -m app.purge_orphan_events --plan
    python -m app.purge_orphan_events
"""
import argparse
import asyncio

from sqlalchemy import func, select

from app.core.database import AsyncSessionFactory
from app.entities.models import Article, Event
from app.services.search_service import SearchService

# An event with no articles should be a rare anomaly. If most of them look
# like this, the join or the article model is wrong, not the corpus.
MAX_MATCH_RATE = 0.10


async def main(plan_only: bool) -> None:
    async with AsyncSessionFactory() as session:
        total = (await session.execute(select(func.count()).select_from(Event))).scalar()
        orphans = (
            await session.execute(
                select(Event).where(
                    ~select(Article.id)
                    .where(Article.event_id == Event.id)
                    .exists()
                )
            )
        ).scalars().all()

        rate = len(orphans) / total if total else 0.0
        print(f"events: {total}")
        print(f"would delete {len(orphans)} ({rate:.1%})")
        for event in orphans:
            print(
                f"  {str(event.id)[:8]} | {event.topic} | "
                f"{(event.summary or '')[:70]}"
            )

        if not orphans:
            print("\nnothing to do.")
            return

        if rate > MAX_MATCH_RATE:
            print(
                f"\nABORT: {rate:.1%} of events are orphaned, above the "
                f"{MAX_MATCH_RATE:.0%} threshold."
            )
            return

        if plan_only:
            print("\nsafe by rate. rerun without --plan to delete.")
            return

        for event in orphans:
            await session.delete(event)
        await session.commit()
        print(f"\ndeleted {len(orphans)} orphan events")

    try:
        indexed, removed = await SearchService().sync_all_processed_events()
        print(f"search synced: {indexed} indexed, {removed} removed")
    except Exception as exc:
        print(f"search sync skipped: {exc}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true", help="report only")
    args = parser.parse_args()
    asyncio.run(main(args.plan))