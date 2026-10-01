"""
GlobeLens AI — ClusteringService
Computes similarity across embeddings to group articles into Events.
Pipeline Step 3: EMBEDDED → CLUSTERED
"""
from typing import List, Tuple, Optional
import uuid
import structlog

from app.core.database import AsyncSessionFactory
from app.entities.models import Event, ProcessingStatus
from app.repositories.article_repository import ArticleRepository
from app.repositories.event_repository import EventRepository
from app.services.article_classifier import is_aggregator_article

logger = structlog.get_logger()


class ClusteringService:
    """
    Groups articles with similar embedding vectors into Event clusters.
    Uses pgvector's built-in similarity operators for efficient database-level search.
    """

    # Cosine distance = 1 - similarity. Measured on this corpus the distance
    # histogram is bimodal: same-story articles from different outlets land
    # between 0.10 and 0.21, and unrelated pairs start at 0.28 and climb past
    # 0.6. 0.25 sits in the gap between those two modes, so it accepts real
    # cross-outlet matches without dragging in unrelated stories.
    SIMILARITY_THRESHOLD_DISTANCE: float = 0.25

    async def cluster_unassigned_articles(self) -> Tuple[int, int]:
        """
        Orchestrator for the clustering pipeline step (EMBEDDED -> CLUSTERED).
        Fetches all unassigned articles, queries pgvector to find closest recent event,
        and assigns the article or starts a new event.
        """
        logger.info("Starting article clustering batch process")
        assigned_to_existing = 0
        new_events_created = 0

        async with AsyncSessionFactory() as session:
            article_repo = ArticleRepository(session)
            event_repo = EventRepository(session)

            try:
                articles_db = await article_repo.get_embedded_unclustered_articles(limit=100)
                # Project ORM objects to simple dictionaries immediately to prevent
                # MissingGreenlet / expired object access errors on loop iterations
                # after a rollback.
                articles = [
                    {
                        "id": art.id,
                        "title": art.title,
                        "vector": art.embedding.vector if art.embedding else None
                    }
                    for art in articles_db
                ]
                logger.info("Fetched unclustered articles for processing", count=len(articles))

                for article in articles:
                    art_id = article["id"]
                    art_title = article["title"]
                    vector = article["vector"]

                    if vector is None or len(vector) == 0:
                        logger.warn("Article missing embedding, skipping clustering", article_id=str(art_id))
                        continue

                    art_obj = await article_repo.find_by_id(art_id)
                    if not art_obj:
                        logger.warn("Article not found, skipping clustering", article_id=str(art_id))
                        continue

                    # Roundups summarise many unrelated stories in one post, so
                    # their vector averages several topics and lands near
                    # unrelated clusters. They get their own event and never
                    # absorb or are absorbed by other articles.
                    if is_aggregator_article(art_obj.title, art_obj.content):
                        new_event = Event(
                            title=art_title,
                            summary=None,
                            status="DRAFT",
                        )
                        session.add(new_event)
                        await session.flush()
                        art_obj.event_id = new_event.id
                        art_obj.processing_status = ProcessingStatus.CLUSTERED
                        await session.commit()
                        new_events_created += 1
                        logger.info(
                            "Aggregator article isolated into its own event",
                            article_id=str(art_id),
                            title=art_title[:60],
                        )
                        continue

                    try:
                        # Find closest event within time window and threshold
                        event_id = await event_repo.find_closest_event_by_vector(
                            vector=vector,
                            threshold=self.SIMILARITY_THRESHOLD_DISTANCE,
                            time_window_hours=72
                        )

                        if event_id:
                            # Match found: assign to existing event
                            art_obj.event_id = event_id
                            art_obj.processing_status = ProcessingStatus.CLUSTERED
                            await session.commit()
                            logger.info(
                                "Assigned article to existing event",
                                article_id=str(art_id),
                                event_id=str(event_id)
                            )
                            assigned_to_existing += 1
                        else:
                            # No match found: create new event using article title as placeholder
                            new_event = Event(
                                title=art_title,
                                summary=None,
                                topic=None,
                                country=None,
                                latitude=None,
                                longitude=None,
                                importance_score=0.0,
                                is_promoted=False
                            )
                            session.add(new_event)
                            await session.flush()  # Hydrate new_event.id

                            art_obj = await article_repo.find_by_id(art_id)
                            if not art_obj:
                                raise ValueError(f"Article with ID {art_id} not found")
                            
                            art_obj.event_id = new_event.id
                            art_obj.processing_status = ProcessingStatus.CLUSTERED
                            await session.commit()
                            logger.info(
                                "Created new event cluster and assigned article",
                                article_id=str(art_id),
                                event_id=str(new_event.id),
                                title=new_event.title
                            )
                            new_events_created += 1

                    except Exception as article_err:
                        logger.error(
                            "Failed to cluster single article",
                            article_id=str(art_id),
                            error=str(article_err)
                        )
                        await session.rollback()
                        continue

                logger.info(
                    "Article clustering batch process completed",
                    assigned_to_existing=assigned_to_existing,
                    new_events_created=new_events_created
                )

            except Exception as batch_err:
                logger.error("Clustering process batch fatal error", error=str(batch_err))
                await session.rollback()

        return assigned_to_existing, new_events_created
