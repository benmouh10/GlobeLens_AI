"""
Destructive re-clustering utility.

Rebuilds the article -> event assignment from scratch at the current
SIMILARITY_THRESHOLD_DISTANCE, then re-runs LLM enrichment over the results.

Embeddings are preserved (they are the expensive part and do not depend on the
threshold), so this only costs one clustering pass plus the LLM synthesis.

Usage:
    python -m app.recluster --yes                # reset, cluster, enrich all
    python -m app.recluster --yes --skip-llm     # reset + cluster only
    python -m app.recluster --plan               # show what would be destroyed
"""

import argparse
import asyncio

import structlog
from sqlalchemy import delete, func, select, update

from app.core.config import settings
from app.core.database import AsyncSessionFactory
from app.entities.models import Article, Embedding, Event
from app.services.clustering_service import ClusteringService
from app.services.article_classifier import classify_topic, topic_is_contradicted
from app.services.geocoding_service import (
    display_name,
    resolve_coordinates,
)
from app.services.llm_service import LLMService
from app.services.search_service import SearchService

logger = structlog.get_logger()


async def reset() -> int:
    """Drop every event and return affected articles to the EMBEDDED pool."""
    async with AsyncSessionFactory() as session:
        count = (await session.execute(select(func.count(Event.id)))).scalar_one()
        await session.execute(delete(Event))
        # Unconditional: a previous run (or the backend's 60s auto-pipeline) can
        # leave articles marked CLUSTERED/PROCESSED with event_id already NULL,
        # and those would never be picked up for re-clustering again.
        result = await session.execute(
            update(Article)
            .values(event_id=None, processing_status="EMBEDDED")
            .where(Article.processing_status != "SCRAPED")
        )
        await session.commit()
        return count, result.rowcount


async def reembed_all() -> int:
    """Recompute every article vector from the capped, title-weighted text.

    Embeddings are cached by content hash, so existing rows must be deleted
    first; otherwise the cache short-circuits and nothing changes.
    """
    from sqlalchemy import delete

    from app.services.embedding_service import EmbeddingService

    async with AsyncSessionFactory() as session:
        await session.execute(delete(Embedding))
        await session.execute(
            update(Article)
            .values(event_id=None, processing_status="SCRAPED")
            .where(Article.processing_status != "SCRAPED")
        )
        await session.commit()

    service = EmbeddingService()
    total = 0
    while True:
        n = await service.process_scraped_batch(limit=25)
        total += n
        if n == 0:
            break
    logger.info(f"Re-embedded {total} articles at {settings.EMBEDDING_MAX_CONTENT_CHARS} char cap")
    return total


async def cluster_all() -> tuple[int, int]:
    """cluster_unassigned_articles() fetches at most 100 rows per call."""
    service = ClusteringService()
    assigned = created = 0
    while True:
        a, c = await service.cluster_unassigned_articles()
        assigned += a
        created += c
        if a + c == 0:
            break
    return assigned, created


async def enrich(max_events: int, concurrency: int) -> tuple[int, int, int]:
    """Enrich not-yet-geocoded events, biggest cross-outlet clusters first.

    LLMService.process_pending_events() walks events 20 at a time with a 5s
    sleep between each, which is far too slow on a CPU-only Ollama host: at
    ~150s/event the full 99-event set is a 4 hour job. This orders by cluster
    size (so the interesting multi-source events land first and are visible in
    the UI even if the run is cut short) and overlaps a few requests.
    """
    import contextlib

    from app.repositories.article_repository import ArticleRepository
    from app.repositories.event_repository import EventRepository
    from app.services.search_service import SearchService

    llm = LLMService()
    search = SearchService()
    sem = asyncio.Semaphore(concurrency)
    tally = {"ok": 0, "fail": 0, "skip": 0}

    async with AsyncSessionFactory() as session:
        rows = (
            await session.execute(
                select(Event.id, func.count(Article.id).label("n"))
                .join(Article, Article.event_id == Event.id)
                .where(Event.latitude.is_(None))
                .group_by(Event.id)
                .order_by(func.count(Article.id).desc(), func.max(Article.published_at).desc())
                .limit(max_events)
            )
        ).all()

    logger.info(f"Enriching {len(rows)} events (concurrency={concurrency})")

    async def worker(event_id) -> None:
        async with sem:
            async with AsyncSessionFactory() as session:
                article_repo = ArticleRepository(session)
                event_repo = EventRepository(session)
                articles = await article_repo.find_by_event(event_id)
                contents = [
                    f"Title: {a.title}\nContent: {a.content}"
                    for a in articles
                    if a.content and a.content.strip()
                ]
                if not contents:
                    tally["skip"] += 1
                    return

                # Topic and country evidence come from the article text, so
                # both are derived from the same joined string.
                event_title = articles[0].title
                joined_text = "\n\n".join(a.content for a in articles if a.content)
                try:
                    intel = await llm.analyze_event_cluster(contents)
                except Exception as exc:
                    tally["fail"] += 1
                    logger.warn(f"LLM failed for {event_id}: {exc}")
                    return

                intel_data = {
                    "summary": intel.summary,
                    "topic": intel.topic.value,
                    "bias_lean": intel.bias_lean.value,
                    "location_country": intel.location_country,
                    "latitude": intel.latitude,
                    "longitude": intel.longitude,
                    "importance_score": intel.importance_score,
                }

                # The 7b model geocoded four unrelated events to downtown
                # Washington DC and tagged a death-penalty story as
                # TECHNOLOGY. Override with keyword/country evidence when we
                # have any, and log what we corrected.
                corrections = []

                # Only override when keyword evidence genuinely contradicts the claim.
                # A plain classify_topic() match is not enough: "government",
                # "protest" and "strike" appear in almost every world story,
                # so 74 of 95 classified articles were being pushed to
                # POLITICS. The contradiction test is the stricter gate.
                geo_topic = classify_topic(event_title, joined_text)
                claimed = intel_data["topic"]
                if geo_topic and geo_topic != claimed and topic_is_contradicted(
                    event_title, joined_text, claimed
                ):
                    corrections.append(f"topic {claimed}->{geo_topic}")
                    intel_data["topic"] = geo_topic
                elif claimed == "TECHNOLOGY" and not classify_topic(
                    event_title, joined_text
                ) == "TECHNOLOGY":
                    # The 7b model over-assigns TECHNOLOGY; if there is no
                    # technology evidence at all, fall back to WORLD.
                    corrections.append("topic TECHNOLOGY->WORLD (no evidence)")
                    intel_data["topic"] = "WORLD"

                # Normalise abbreviations the model sometimes returns ("US", "USA", "UK")
                # so the stored country matches the geocoder's table.
                raw_country = (intel_data["location_country"] or "").strip()
                canon = display_name(raw_country)
                if canon and canon != raw_country:
                    corrections.append(f"country {raw_country}->{canon}")
                    intel_data["location_country"] = canon

                # Re-resolving here means a newly-added country is picked up
                # without re-running the LLM: enrich events that already have
                # coordinates but whose country is Global or unknown.
                lat, lon, geo_note = resolve_coordinates(
                    intel_data["location_country"],
                    intel.latitude,
                    intel.longitude,
                )
                if geo_note and intel.latitude is not None:
                    corrections.append(f"geo {geo_note}")
                intel_data["latitude"] = lat
                intel_data["longitude"] = lon

                await event_repo.update_event_intelligence(event_id, intel_data)
                tally["ok"] += 1
                logger.info(
                    f"enriched {str(event_id)[:8]} ({len(contents)} articles) "
                    f"topic={intel_data['topic']} "
                    f"country={intel_data['location_country']} "
                    f"lat={intel_data['latitude']}"
                    + (f" CORRECTED[{'; '.join(corrections)}]" if corrections else "")
                )

    # gather() short-circuits on the first exception, and wrapping it in
    # contextlib.suppress hid the traceback: the run reported
    # "Enriched 0 events, 0 failed, 0 skipped" with no indication of why.
    # return_exceptions=True lets every worker finish and is logged.
    results = await asyncio.gather(
        *(worker(r[0]) for r in rows), return_exceptions=True
    )
    for r in results:
        if isinstance(r, BaseException):
            tally["fail"] += 1
            logger.error("enrichment worker crashed", error=repr(r))

    # Re-sync the search index. Enrichment updates Postgres directly, so
    # without this the map's search path keeps serving pre-enrichment
    # documents (no coordinates, stale topics).
    if tally["ok"]:
        try:
            indexed, removed = await search.sync_all_processed_events()
            logger.info(f"search synced: {indexed} indexed, {removed} removed")
        except Exception as sync_err:
            logger.error("search sync failed", error=str(sync_err))

    return tally["ok"], tally["fail"], tally["skip"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="confirm the destructive reset")
    parser.add_argument("--skip-llm", action="store_true", help="stop after clustering")
    parser.add_argument("--plan", action="store_true", help="report and exit, no changes")
    parser.add_argument(
        "--reembed",
        action="store_true",
        help="recompute every embedding from the capped text before clustering",
    )
    parser.add_argument(
        "--enrich-only",
        action="store_true",
        help="keep existing clusters, just enrich events still missing coordinates",
    )
    parser.add_argument("--max", type=int, default=40, help="cap how many events to enrich")
    parser.add_argument("--concurrency", type=int, default=3, help="parallel LLM requests")
    args = parser.parse_args()

    logger.info(
        f"Threshold: {ClusteringService.SIMILARITY_THRESHOLD_DISTANCE}  "
        f"LLM: {LLMService()._model}"
    )

    if args.plan:
        asyncio.run(_report())
        return

    if args.reembed:
        if not args.yes:
            logger.info("Refusing to re-embed: this drops all embeddings and events. Pass --yes.")
            return
        asyncio.run(_reembed_and_cluster(args))
        return

    if args.enrich_only:
        ok, fail, skip = asyncio.run(enrich(args.max, args.concurrency))
        logger.info(f"Enriched {ok} events, {fail} failed, {skip} skipped")
        return

    asyncio.run(_run(args))


async def _reembed_and_cluster(args) -> None:
    n = await reembed_all()
    dropped, requeued = await reset()
    logger.warn(f"Dropped {dropped} events, re-queued {requeued} articles.")

    assigned, created = await cluster_all()
    logger.info(f"Clustered: {assigned} assigned, {created} new events (from {n} re-embedded)")

    if args.skip_llm:
        return

    ok, fail, skip = await enrich(args.max, args.concurrency)
    logger.info(f"Enriched {ok} events, {fail} failed, {skip} skipped")


async def _report() -> None:
    async with AsyncSessionFactory() as session:
        articles = (await session.execute(select(func.count(Article.id)))).scalar_one()
        events = (await session.execute(select(func.count(Event.id)))).scalar_one()
        mapped = (
            await session.execute(
                select(func.count(Event.id)).where(Event.latitude.isnot(None))
            )
        ).scalar_one()
    logger.info(
        f"Would delete {events} events ({mapped} enriched, {articles} articles). "
        "Embeddings are kept, so only the LLM pass is re-paid."
    )


if __name__ == "__main__":
    main()