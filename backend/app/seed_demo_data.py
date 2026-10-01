"""
GlobeLens AI — Demo data seeder

Populates an empty database with a small, real dataset so the frontend map,
feed, search and chatbot have something to render.

Unlike ScraperService.run_pipeline (which ingests every item from every feed),
this script caps each stage, because the stages have very different costs:

  RSS discovery      cheap          seconds
  Playwright extract ~5-10s each    dominates the scrape stage
  bge-m3 embedding   ~5s each       serial on CPU
  LLM synthesis      ~90s per event dominates everything

The default budget is deliberately small. Override with the env vars below.

Usage (from the backend container):
    python -m app.seed_demo_data

Env vars:
    SEED_ARTICLES_PER_SOURCE   articles to ingest per publisher (default 3)
    SEED_MAX_EVENTS            events to send through LLM synthesis (default 4)
    SEED_SKIP_PLAYWRIGHT       1 = use RSS descriptions instead of a real
                               browser fetch (much faster, thinner content)
    SEED_SOURCES               "Name1|https://a1,Name2|https://a2"
"""
import asyncio
import os
import time
from typing import List

import structlog
from sqlalchemy import select

from app.core.database import AsyncSessionFactory
from app.core.config import settings
from app.entities.models import Source, Article, Event, Embedding, BiasLean
from app.repositories.article_repository import ArticleRepository
from app.services.scraper_service import ScraperService
from app.services.embedding_service import EmbeddingService
from app.services.clustering_service import ClusteringService
from app.services.llm_service import LLMService
from app.services.search_service import SearchService

logger = structlog.get_logger()

ARTICLES_PER_SOURCE = int(os.getenv("SEED_ARTICLES_PER_SOURCE", "3"))
MAX_EVENTS = int(os.getenv("SEED_MAX_EVENTS", "4"))
SKIP_PLAYWRIGHT = os.getenv("SEED_SKIP_PLAYWRIGHT", "0") == "1"

DEFAULT_SOURCES = [
    ("BBC News", "https://www.bbc.com/news", "United Kingdom", 0.90, BiasLean.CENTER),
    ("CNN", "https://www.cnn.com", "United States", 0.75, BiasLean.CENTER_LEFT),
    ("Al Jazeera", "https://www.aljazeera.com", "Qatar", 0.80, BiasLean.CENTER),
]


def _configured_sources() -> List[tuple]:
    raw = os.getenv("SEED_SOURCES")
    if not raw:
        return DEFAULT_SOURCES
    parsed = []
    for pair in raw.split(","):
        if "|" not in pair:
            continue
        name, url = pair.split("|", 1)
        parsed.append((name.strip(), url.strip(), None, 0.5, BiasLean.CENTER))
    return parsed or DEFAULT_SOURCES


async def seed_sources() -> int:
    """Insert the publisher list, skipping any name already present."""
    created = 0
    async with AsyncSessionFactory() as session:
        for name, url, country, credibility, bias in _configured_sources():
            existing = await session.execute(select(Source).where(Source.name == name))
            if existing.scalars().first():
                logger.info("Source already present, skipping", source_name=name)
                continue
            session.add(Source(
                name=name,
                url=url,
                country=country,
                credibility_score=credibility,
                bias_lean=bias,
            ))
            created += 1
        await session.commit()
    logger.info("Sources ready", created=created)
    return created


async def seed_articles() -> int:
    """Ingest a capped number of articles per publisher via RSS."""
    scraper = ScraperService()
    inserted = 0

    async with AsyncSessionFactory() as session:
        sources = (await session.execute(select(Source))).scalars().all()
        repo = ArticleRepository(session)

        for source in sources:
            rss_url = scraper._resolve_rss_url(source.name, source.url)
            items = await scraper.fetch_rss_links(rss_url)
            if not items:
                logger.warn("No RSS items returned", source_name=source.name, rss_url=rss_url)
                continue

            for item in items[:ARTICLES_PER_SOURCE]:
                existing = await session.execute(
                    select(Article).where(Article.url == item["url"])
                )
                if existing.scalars().first():
                    continue

                if SKIP_PLAYWRIGHT:
                    content = item["title"]
                else:
                    try:
                        content = await scraper.extract_full_content(item["url"])
                    except Exception as err:
                        logger.warn("Extraction failed, skipping", url=item["url"], error=str(err))
                        continue

                if not content or not content.strip():
                    continue

                article = await repo.create_scraped_article({
                    "title": item["title"],
                    "url": item["url"],
                    "published_at": item["published_at"],
                    "content": content,
                    "source_id": str(source.id),
                })
                if article:
                    inserted += 1
                    logger.info("Ingested article", title=item["title"][:70], source=source.name)

    logger.info("Articles ingested", inserted=inserted)
    return inserted


async def report() -> None:
    async with AsyncSessionFactory() as session:
        counts = {}
        for label, model in (("sources", Source), ("articles", Article),
                             ("embeddings", Embedding), ("events", Event)):
            counts[label] = len((await session.execute(select(model))).scalars().all())

        located = (await session.execute(
            select(Event).where(Event.latitude.isnot(None))
        )).scalars().all()

    print("\n" + "=" * 58)
    print("  GlobeLens AI — seed summary")
    print("=" * 58)
    for label, value in counts.items():
        print(f"  {label:<12} {value}")
    print(f"  {'mappable':<12} {len(located)}  (events with coordinates)")
    print("=" * 58 + "\n")


async def main() -> None:
    started = time.time()
    print(f"\nProviders: LLM={settings.LLM_PROVIDER}  "
          f"EMBEDDING={settings.EMBEDDING_PROVIDER}  "
          f"dims={settings.EMBEDDING_DIMENSIONS}")
    print(f"Playwright extraction: {'disabled' if SKIP_PLAYWRIGHT else 'enabled'}")
    print(f"Budget: {ARTICLES_PER_SOURCE} articles/source, {MAX_EVENTS} events through LLM\n")

    await seed_sources()
    await seed_articles()

    print("-> embedding (bge-m3 via Ollama)")
    embedded = await EmbeddingService().process_scraped_batch(limit=100)
    print(f"   embedded {embedded}")

    print("-> clustering (pgvector cosine)")
    assigned, created = await ClusteringService().cluster_unassigned_articles()
    print(f"   assigned to existing: {assigned}, new events: {created}")

    print(f"-> LLM synthesis (up to {MAX_EVENTS} events, ~90s each)")
    # process_pending_events takes a limit internally; cap by trimming afterwards
    # is not possible, so drive it directly for a bounded number of events.
    llm = LLMService()
    processed = 0
    async with AsyncSessionFactory() as session:
        from app.repositories.event_repository import EventRepository
        event_repo = EventRepository(session)
        article_repo = ArticleRepository(session)
        pending = await event_repo.get_unprocessed_events(limit=MAX_EVENTS)

        for event in pending:
            arts = await article_repo.find_by_event(event.id)
            blobs = [f"Title: {a.title}\nContent: {a.content}"
                     for a in arts if a.content and a.content.strip()]
            if not blobs:
                continue
            print(f"   [{processed + 1}/{len(pending)}] {event.title[:58]}")
            intelligence = await llm.analyze_event_cluster(blobs)
            await event_repo.update_event_intelligence(event.id, {
                "summary": intelligence.summary,
                "topic": intelligence.topic.value,
                "bias_lean": intelligence.bias_lean.value,
                "location_country": intelligence.location_country,
                "latitude": intelligence.latitude,
                "longitude": intelligence.longitude,
                "importance_score": intelligence.importance_score,
            })
            processed += 1
            print(f"        -> {intelligence.location_country} "
                  f"({intelligence.latitude}, {intelligence.longitude}) "
                  f"imp={intelligence.importance_score}")

    print(f"   processed {processed}")

    print("-> Elasticsearch sync")
    try:
        indexed, failed = await SearchService().sync_all_processed_events()
        print(f"   indexed {indexed}, failed {failed}")
    except Exception as err:
        logger.warn("Search sync failed (non-fatal)", error=str(err))

    await report()
    print(f"Total elapsed: {time.time() - started:.0f}s\n")


if __name__ == "__main__":
    asyncio.run(main())
