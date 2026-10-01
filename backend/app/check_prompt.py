"""
Ad-hoc validation for the tightened analyze_event_cluster prompt.

Runs the real LLMService against a handful of live events, including the two
known-bad ones, and reports whether the prompt now (a) produces valid JSON,
(b) omits fabricated coordinates, and (c) gets the topic right.

Not part of the app; delete once the prompt is trusted.
"""
import asyncio

from sqlalchemy import select

from app.core.database import AsyncSessionFactory
from app.entities.models import Article, Event
from app.services.article_classifier import classify_topic, topic_is_contradicted
from app.services.geocoding_service import resolve_coordinates
from app.services.llm_service import LLMService

# Events that previously came out wrong.
TARGET_TITLES = [
    "US Supreme Court denies Christa Pike",
    "Kashmir",
    "Ethiopia: No regard for civilians",
    "U.S. military withdraws from Iraq",
    "Denmark vs Portugal",
    "A pilot stabs the other pilot",
]


async def main() -> None:
    async with AsyncSessionFactory() as session:
        events = (await session.execute(select(Event))).scalars().all()

    chosen = []
    for needle in TARGET_TITLES:
        for event in events:
            if needle.lower() in (event.title or "").lower():
                chosen.append(event)
                break

    llm = LLMService()

    for event in chosen:
        async with AsyncSessionFactory() as session:
            articles = (
                await session.execute(
                    select(Article).where(Article.event_id == event.id)
                )
            ).scalars().all()

        if not articles:
            continue

        contents = [
            f"Title: {a.title}\nContent: {a.content}"
            for a in articles
            if a.content and a.content.strip()
        ]
        joined = "\n\n".join(a.content for a in articles if a.content)

        try:
            intel = await llm.analyze_event_cluster(contents)
        except Exception as exc:
            print(f"  {event.title[:40]:42s} FAILED: {str(exc)[:60]}")
            continue

        topic = intel.topic.value
        corrected = classify_topic(event.title, joined)
        geo_lat, geo_lon, note = resolve_coordinates(
            intel.location_country, intel.latitude, intel.longitude
        )

        flag = ""
        if corrected and corrected != topic:
            flag = f"  [{topic}->{corrected}]"
        if intel.latitude is not None:
            flag += "  [LLM still returned coords!]"

        print(
            f"  {event.title[:40]:42s} topic={topic:11s} "
            f"country={intel.location_country:16s} "
            f"geo={geo_lat},{geo_lon}{flag}"
        )
        if note:
            print(f"      geo note: {note[:78]}")


if __name__ == "__main__":
    asyncio.run(main())