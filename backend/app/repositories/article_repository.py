"""
GlobeLens AI — ArticleRepository
Async SQLAlchemy repository for Article entity persistence and retrieval.
"""
import uuid
from typing import List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.entities.models import Article, ProcessingStatus


class ArticleRepository:
    """
    Data access layer for the Article entity.
    All methods accept an AsyncSession injected by FastAPI dependency injection.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, article: Article) -> Article:
        """Insert or update an Article record."""
        self._session.add(article)
        await self._session.commit()
        await self._session.refresh(article)
        return article

    async def find_by_id(self, article_id: uuid.UUID) -> Optional[Article]:
        """Fetch a single article by primary key."""
        return await self._session.get(Article, article_id)

    async def find_unprocessed(self, status: ProcessingStatus) -> List[Article]:
        """Return all articles at a given processing stage for pipeline workers."""
        result = await self._session.execute(
            select(Article).where(Article.processing_status == status)
        )
        return list(result.scalars().all())

    async def find_by_event(self, event_id: uuid.UUID) -> List[Article]:
        """Return all articles belonging to a given Event, in citation order.

        The order is not cosmetic. Event summaries cite sources as [1], [2]...
        where the number is the position of the article in this list, and the
        frontend resolves [2] as the second article the API returns. Both sides
        must agree on a total order or a citation points at the wrong article.
        published_at is the sort a reader expects; id breaks the tie because
        scraped articles can share a timestamp.
        """
        result = await self._session.execute(
            select(Article)
            .where(Article.event_id == event_id)
            .order_by(
                Article.published_at.asc().nulls_last(),
                Article.id.asc(),
            )
        )
        return list(result.scalars().all())

    async def update_status(
        self, article_id: uuid.UUID, status: ProcessingStatus
    ) -> None:
        """Efficiently update only the processing_status column."""
        await self._session.execute(
            update(Article)
            .where(Article.id == article_id)
            .values(processing_status=status)
        )
        await self._session.commit()

    async def create_scraped_article(
        self, article_data: dict
    ) -> Optional[Article]:
        """
        Create and persist a scraped article.
        Checks for URL uniqueness; returns None if it's a duplicate.
        """
        # Idempotency check against URL
        result = await self._session.execute(
            select(Article).where(Article.url == article_data["url"])
        )
        existing = result.scalars().first()
        if existing:
            # Skip transaction safely without committing to prevent duplicates
            return None

        # Resolve published_at if present
        published_at = article_data.get("published_at")

        # Check source_id if present
        source_id = article_data.get("source_id")
        if isinstance(source_id, str):
            source_id = uuid.UUID(source_id)

        article = Article(
            title=article_data["title"],
            content=article_data.get("content"),
            url=article_data["url"],
            published_at=published_at,
            processing_status=ProcessingStatus.SCRAPED,
            source_id=source_id,
            is_hidden=False
        )

        self._session.add(article)
        await self._session.commit()
        await self._session.refresh(article)
        return article

    async def get_unprocessed_articles(self, limit: int = 50) -> List[Article]:
        """Fetch articles with status SCRAPED up to a specified limit."""
        result = await self._session.execute(
            select(Article)
            .where(Article.processing_status == ProcessingStatus.SCRAPED)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_embedded_unclustered_articles(self, limit: int = 100) -> List[Article]:
        """Fetch articles with status EMBEDDED, eagerly loading their embeddings, up to a specified limit."""
        result = await self._session.execute(
            select(Article)
            .options(joinedload(Article.embedding))
            .where(Article.processing_status == ProcessingStatus.EMBEDDED)
            .limit(limit)
        )
        return list(result.scalars().all())

