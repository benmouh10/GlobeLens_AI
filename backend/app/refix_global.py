"""
One-off: re-run enrichment for events whose country is Global but which are
not genuinely placeless.

Seven events sat at Global after enrichment. Four are correct (three Euronews
bulletins covering many countries, one hurricane spanning Hawaii and Baja).
The other two named a country the model failed to commit to: a Cornell
(University of New York) investigation and an Irish Eurovision boycott.

Retrying those two with the title emphasised, because the model defaults to
Global when it cannot place a story and the title is where the country usually
is. Events left at Global after this pass are genuinely multi-region and stay
unmapped by design.

    python -m app.refix_global --plan
    python -m app.refix_global
"""
import argparse
import asyncio
import contextlib

from sqlalchemy import select

from app.core.database import AsyncSessionFactory
from app.entities.models import Article, Event
from app.repositories.event_repository import EventRepository
from app.services.article_classifier import classify_topic, topic_is_contradicted
from app.services.geocoding_service import (
    country_from_text,
    display_name,
    resolve_coordinates,
)
from app.services.llm_service import LLMService
from app.services.search_service import SearchService

# Substrings identifying events with no single country. Retrying a Euronews
# bulletin wastes several minutes of CPU and always lands on Global again.
PLACELESS_HINTS = (
    "latest news bulletin",
    "hurricane",
    "bulletin",
)


def is_placeless(title: str, summary: str) -> bool:
    haystack = f"{title} {summary}".lower()
    return any(hint in haystack for hint in PLACELESS_HINTS)


async def main(plan_only: bool) -> None:
    async with AsyncSessionFactory() as session:
        events = (
            await session.execute(select(Event).where(Event.latitude.is_(None)))
        ).scalars().all()

        candidates = []
        skipped = []
        for event in events:
            if is_placeless(event.title or "", event.summary or ""):
                skipped.append(event)
            else:
                candidates.append(event)

        print(f"unmapped: {len(events)}")
        print(f"retry: {len(candidates)}")
        print(f"leave alone (placeless): {len(skipped)}")
        for event in candidates:
            print(f"  retry  {str(event.id)[:8]} | {(event.title or '')[:66]}")
        for event in skipped:
            print(f"  skip   {str(event.id)[:8]} | {(event.title or '')[:66]}")

        if plan_only:
            print("\nplan only; nothing changed.")
            return

    llm = LLMService()
    fixed = 0

    for event in candidates:
        async with AsyncSessionFactory() as session:
            row = await session.get(Event, event.id)
            if row is None:
                continue
            articles = (
                await session.execute(
                    select(Article).where(Article.event_id == row.id)
                )
            ).scalars().all()

            contents = []
            for article in articles:
                body = (article.content or "").strip()
                if len(body) <= 400:
                    continue
                contents.append(f"Title: {article.title}\nContent: {body}")

            if not contents:
                print(f"skip {str(row.id)[:8]}: no usable article body")
                continue

            joined = "\n\n".join(
                (a.content or "") for a in articles if a.content
            )

            intel = None
            with contextlib.suppress(Exception):
                intel = await llm.analyze_event_cluster(contents)

            if intel is None:
                print(f"failed {str(row.id)[:8]}: LLM error")
                continue

            # Work from the raw string, not display_name: "Global" is not a key in the
            # country table, so display_name("Global") is None, and comparing
            # against "Global" after mapping never matched.
            raw_country = intel.location_country
            second: str | None = None

            # The main synthesis calls Global whenever it has to write three
            # paragraphs and a country at once. Ask again with one field.
            if not raw_country or raw_country.strip().lower() == "global":
                second = await llm.resolve_primary_country(
                    row.title or "", joined
                )
                if second and second.strip().lower() != "global":
                    raw_country = second

            # Last resort: scan the headline. The second pass is inconsistent
            # run to run on the same article, so it cannot be trusted to agree
            # with itself. Not applied to the skipped placeless events, and the
            # scan would pin a hurricane to one of the two countries it
            # threatens, so it stays a fallback rather than a rule.
            if not raw_country or raw_country.strip().lower() == "global":
                scanned = country_from_text(row.title or "")
                if scanned:
                    raw_country = scanned

            country = display_name(raw_country)
            lat, lon, _ = resolve_coordinates(country, None, None)

            if lat is None:
                print(
                    f"still global {str(row.id)[:8]}: "
                    f"synthesis said {intel.location_country!r}, "
                    f"second pass said {second!r}"
                )
                continue

            topic = intel.topic.value
            keyword = classify_topic(row.title, joined)
            if (
                keyword
                and keyword != topic
                and topic_is_contradicted(row.title, joined, topic)
            ):
                topic = keyword

            await EventRepository(session).update_event_intelligence(
                row.id,
                {
                    "summary": intel.summary,
                    "topic": topic,
                    "bias_lean": intel.bias_lean.value,
                    "location_country": country,
                    "latitude": lat,
                    "longitude": lon,
                    "importance_score": intel.importance_score,
                },
            )
            await session.commit()
            fixed += 1
            print(f"fixed {str(row.id)[:8]} -> {country} {lat},{lon} ({topic})")

    print(f"\nfixed {fixed} of {len(candidates)}")

    with contextlib.suppress(Exception):
        indexed, removed = await SearchService().sync_all_processed_events()
        print(f"search synced: {indexed} indexed, {removed} removed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true", help="report only")
    args = parser.parse_args()
    asyncio.run(main(args.plan))