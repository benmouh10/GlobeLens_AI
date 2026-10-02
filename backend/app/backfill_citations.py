"""
One-off: attach citations to already-stored summaries.

The two-pass change does not require re-synthesis. Attribute citations need
the existing summary and the source titles, both of which are already in the
database, so this rewrites only the summary text and leaves topic, country,
coordinates and scores untouched.

89 of 101 events have a single source, where the only possible citation is [1]
and no model call is needed. The remaining multi-source events get one
title-only attribution call each.

    python -m app.backfill_citations --plan
    python -m app.backfill_citations
"""
import argparse
import asyncio
import contextlib
import re

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionFactory
from app.entities.models import Article, Event
from app.services.llm_service import LLMService
from app.services.search_service import SearchService

CITE = re.compile(r"\s*\[(\d+)\]\s*")

# Events per run is bounded so a long job stays resumable.
BATCH = 20


def strip_citations(text: str) -> str:
    """Remove existing markers so this is safe to re-run."""
    paragraphs = [
        CITE.sub("", p).strip()
        for p in text.replace("\r\n", "\n").split("\n\n")
        if p.strip()
    ]
    return "\n\n".join(paragraphs)


def cited(text: str) -> bool:
    return bool(CITE.search(text or ""))


async def main(plan_only: bool) -> None:
    async with AsyncSessionFactory() as session:
        total = (await session.execute(select(func.count()).select_from(Event))).scalar()
        already = (
            await session.execute(
                select(func.count()).select_from(Event).where(Event.summary.ilike("%[%]"))
            )
        ).scalar()

        events = (
            await session.execute(
                select(Event)
                .options(selectinload(Event.articles).selectinload(Article.source))
                .where(Event.summary.isnot(None))
            )
        ).scalars().all()

        needs_llm = []
        single = []
        done = []
        for event in events:
            sources = [a for a in event.articles if a.content and a.content.strip()]
            if not event.summary or not sources:
                continue
            if cited(event.summary):
                done.append(event)
            elif len(sources) == 1:
                single.append(event)
            else:
                needs_llm.append(event)

        print(f"events: {total}")
        print(f"already cited: {len(done)}")
        print(f"single-source (no model call): {len(single)}")
        print(f"multi-source (one call each): {len(needs_llm)}")
        print(f"summary rows matching [1] in db: {already}")

        if plan_only:
            print("\nplan only; nothing changed.")
            return

    if single:
        async with AsyncSessionFactory() as session:
            for event in single:
                row = await session.get(Event, event.id)
                if row is None:
                    continue
                body = strip_citations(row.summary or "")
                paragraphs = [p for p in body.split("\n\n") if p.strip()]
                rendered = "\n\n".join(f"{p} [1]" for p in paragraphs)
                row.summary = rendered
            await session.commit()
        print(f"single-source: cited {len(single)} without inference")

    if needs_llm:
        llm = LLMService()
        ok = skipped = 0
        for start in range(0, len(needs_llm), BATCH):
            chunk = needs_llm[start : start + BATCH]
            for event in chunk:
                async with AsyncSessionFactory() as session:
                    # selectinload, not session.get: touching row.articles
                    # would lazy-load inside async context and raise
                    # MissingGreenlet.
                    row = (
                        await session.execute(
                            select(Event)
                            .options(selectinload(Event.articles))
                            .where(Event.id == event.id)
                        )
                    ).scalars().first()
                    if row is None:
                        skipped += 1
                        continue
                    titles = [
                        a.title
                        for a in row.articles
                        if a.content and a.content.strip() and a.title
                    ]
                    if not titles:
                        skipped += 1
                        continue

                    attributed = None
                    with contextlib.suppress(Exception):
                        attributed = await llm.attribute_sources(
                            strip_citations(row.summary or ""), titles
                        )

                    if attributed and cited(attributed):
                        row.summary = attributed
                        ok += 1
                    else:
                        # Leave the summary uncited rather than invent markers.
                        skipped += 1

                    # Commit inside this session. A separate commit after the
                    # loop discarded every write, because the session holding
                    # the changes had already been closed and rolled back.
                    await session.commit()
                print(f"  {chunk.index(event) + start + 1}/{len(needs_llm)}", end="\r")
        print(f"\nmulti-source: cited {ok}, left uncited {skipped}")

    with contextlib.suppress(Exception):
        indexed, removed = await SearchService().sync_all_processed_events()
        print(f"search synced: {indexed} indexed, {removed} removed")

    async with AsyncSessionFactory() as session:
        # Count summaries containing any bracketed number, not just [1]: a
        # multi-source paragraph may cite [2] alone.
        after = (
            await session.execute(
                select(func.count()).select_from(Event).where(Event.summary.ilike("%[%]"))
            )
        ).scalar()
        print(f"cited events now: {after}/{total}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true", help="report only")
    args = parser.parse_args()
    asyncio.run(main(args.plan))