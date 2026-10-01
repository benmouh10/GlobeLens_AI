"""
One-off: re-resolve coordinates for events that already have intelligence.

Adding countries to the geocoder should not require re-running the LLM over
every event, because the model's output (country, summary, topic) is already
stored. This recomputes only latitude/longitude from the stored country, and
retries the LLM only for the small set of events whose country is Global or
missing from the table.

    python -m app.regeocode --plan              # report only, changes nothing
    python -m app.regeocode                     # re-resolve from stored country
    python -m app.regeocode --redo-global       # also retry Global events (slow,
                                               # runs the LLM per event)
"""
import argparse
import asyncio
import contextlib

from sqlalchemy import select

from app.core.database import AsyncSessionFactory
from app.entities.models import Event
from app.repositories.article_repository import ArticleRepository
from app.services.geocoding_service import display_name, resolve_coordinates
from app.services.llm_service import LLMService
from app.services.search_service import SearchService

# A geocoder table covering nearly every country should place almost
# everything. If the plan claims to re-pin most of the corpus, the anchors or
# the country table are wrong, and applying it would scatter valid markers.
MAX_CHANGE_RATE = 0.50


async def survey(redo_global: bool) -> tuple[list, list, list]:
    """Return (unplaceable, would_change, total_events)."""
    unplaceable: list = []
    would_change: list = []

    async with AsyncSessionFactory() as session:
        events = (await session.execute(select(Event))).scalars().all()

        for event in events:
            canon = display_name((event.country or "").strip())
            lat, lon, _ = resolve_coordinates(canon, None, None)

            if lat is None:
                unplaceable.append((event, (event.country or "").strip()))
                continue

            if event.latitude != lat or event.longitude != lon:
                would_change.append(
                    (
                        event,
                        canon,
                        (event.latitude, event.longitude),
                        (lat, lon),
                    )
                )

    return unplaceable, would_change, events


def report(unplaceable, would_change, total) -> bool:
    print(f"events: {total}")
    print(f"would re-pin {len(would_change)} ({len(would_change)/total if total else 0:.1%})")
    print(f"still unplaceable: {len(unplaceable)}")
    for event, country in unplaceable:
        print(f"  unmapped {str(event.id)[:8]} | {country!r}")

    for event, canon, old, new in would_change:
        print(
            f"  move {str(event.id)[:8]} {canon} "
            f"{old[0]},{old[1]} -> {new[0]},{new[1]}"
        )

    if not would_change and not unplaceable:
        print("\nnothing to do.")
        return True

    rate = len(would_change) / total if total else 0
    if rate > MAX_CHANGE_RATE:
        print(
            f"\nABORT: would move {rate:.0%} of events, above the "
            f"{MAX_CHANGE_RATE:.0%} threshold. Re-pinning this much usually "
            f"means the anchor table is wrong, not that the corpus is."
        )
        return False

    print("\nsafe by rate. rerun without --plan to apply.")
    return True


async def main(plan_only: bool, redo_global: bool) -> None:
    unplaceable, would_change, events = await survey(redo_global)

    if plan_only:
        report(unplaceable, would_change, len(events))
        return

    if not report(unplaceable, would_change, len(events)):
        return

    llm = LLMService()
    search = SearchService()
    pinned = regeoed = 0

    for event, canon, old, new in would_change:
        async with AsyncSessionFactory() as session:
            row = await session.get(Event, event.id)
            if row is None:
                continue
            row.country = canon
            row.latitude = new[0]
            row.longitude = new[1]
            await session.commit()
            pinned += 1
            print(f"pinned {str(event.id)[:8]} {canon} -> {new[0]},{new[1]}")

    if redo_global:
        for event, country in unplaceable:
            async with AsyncSessionFactory() as session:
                row = await session.get(Event, event.id)
                if row is None:
                    continue
                articles = await ArticleRepository(session).find_by_event(event.id)
                contents = [
                    f"Title: {a.title}\nContent: {a.content}"
                    for a in articles
                    if a.content and len(a.content.strip()) > 400
                ]
                if not contents:
                    continue

                with contextlib.suppress(Exception):
                    intel = await llm.analyze_event_cluster(contents)
                    guess = display_name(intel.location_country)
                    lat, lon, _ = resolve_coordinates(guess, None, None)
                    if lat is not None:
                        row.country = guess
                        row.latitude = lat
                        row.longitude = lon
                        await session.commit()
                        regeoed += 1
                        print(
                            f"regeocoded {str(event.id)[:8]} {country} "
                            f"-> {guess} {lat},{lon}"
                        )

    print(f"\ndone: {pinned} pinned, {regeoed} re-geocoded")

    with contextlib.suppress(Exception):
        indexed, removed = await search.sync_all_processed_events()
        print(f"search synced: {indexed} indexed, {removed} removed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan",
        action="store_true",
        help="report what would change and modify nothing",
    )
    parser.add_argument(
        "--redo-global",
        action="store_true",
        help="also retry events with no placeable country (runs the LLM)",
    )
    args = parser.parse_args()
    asyncio.run(main(args.plan, args.redo_global))