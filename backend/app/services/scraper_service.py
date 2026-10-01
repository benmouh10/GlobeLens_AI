"""
GlobeLens AI — ScraperService
Handles automated, fault-tolerant news ingestion from BBC, CNN, and Al Jazeera
using a hybrid RSS discovery + Playwright browser hydration + BeautifulSoup parsing pipeline.
"""
import calendar
import time
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import httpx
import feedparser
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import structlog
from sqlalchemy import select

from app.core.database import AsyncSessionFactory
from app.entities.models import Source, Article
from app.repositories.article_repository import ArticleRepository

logger = structlog.get_logger()

# Mapping publisher homepages/names to their standard RSS feeds
RSS_FEED_MAPPING = {
    "bbc news": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "bbc": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "cnn": "http://rss.cnn.com/rss/edition.rss",
    "al jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
    "aljazeera": "https://www.aljazeera.com/xml/rss/all.xml"
}

class ScraperService:
    """
    Service responsible for RSS discovery and scraping using Playwright + BeautifulSoup.
    """

    # Bot-protection and error interstitials are served with HTTP 200, so the
    # status code looks fine and the body is a handful of short paragraphs.
    # Without this check those pages pass the "non-empty" test and get stored
    # as articles, which then pollutes the embedding space and the clustering
    # distance distribution.
    BLOCK_PAGE_SIGNATURES = (
        "reference #",
        "errors.edgesuite.net",
        "access denied",
        "attention required",
        "enable javascript and cookies to continue",
        "checking your browser before accessing",
        "request blocked",
        "captcha",
        "cf-browser-verification",
        "just a moment",
        "incapsula incident id",
        # CNN serves this stub instead of an article when it decides the
        # request looks automated. It is ~120 chars, below MIN_ARTICLE_CHARS,
        # but that length check was evidently not applied on every insert
        # path, so three of these were stored and later summarised as
        # "The article is a placeholder for a QR code document".
        "scan the qr code",
        "download the cnn app",
    )

    # Real articles run well past this; every interstitial seen so far is <400.
    MIN_ARTICLE_CHARS = 400

    def _reject_if_blocked(self, content: str, url: str) -> Optional[str]:
        """Return a rejection reason if the extracted text is not a real article."""
        lowered = content.lower()
        for signature in self.BLOCK_PAGE_SIGNATURES:
            if signature in lowered:
                return f"block-page signature {signature!r}"

        if len(content.strip()) < self.MIN_ARTICLE_CHARS:
            return f"only {len(content.strip())} chars extracted"

        return None

    def _resolve_rss_url(self, source_name: str, source_url: str) -> str:
        """Resolve the homepage URL of a source to its RSS feed endpoint."""
        name_key = source_name.lower().strip()
        if name_key in RSS_FEED_MAPPING:
            return RSS_FEED_MAPPING[name_key]
        
        # Dialect matching / fallback
        if "bbc" in source_url:
            return "https://feeds.bbci.co.uk/news/world/rss.xml"
        if "cnn" in source_url:
            return "http://rss.cnn.com/rss/edition.rss"
        if "aljazeera" in source_url:
            return "https://www.aljazeera.com/xml/rss/all.xml"
            
        return source_url

    async def fetch_rss_links(self, rss_url: str) -> List[Dict[str, Any]]:
        """
        Fetches RSS feed items and returns a list of dictionaries with metadata.
        """
        logger.info("Fetching RSS feed articles", rss_url=rss_url)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(rss_url)
                response.raise_for_status()
                
            # Parse XML feed
            feed = feedparser.parse(response.text)
            articles = []
            
            for entry in feed.entries:
                title = entry.get("title", "Untitled")
                link = entry.get("link")
                if not link:
                    continue
                
                # Convert time.struct_time to timezone-aware datetime (UTC)
                published_parsed = entry.get("published_parsed") or entry.get("updated_parsed")
                if published_parsed:
                    ts = calendar.timegm(published_parsed)
                    published_at = datetime.fromtimestamp(ts, tz=timezone.utc)
                else:
                    published_at = datetime.now(timezone.utc)
                    
                articles.append({
                    "title": title,
                    "url": link,
                    "published_at": published_at
                })
                
            logger.info("RSS parsing complete", rss_url=rss_url, count=len(articles))
            return articles
        except Exception as e:
            logger.error("Failed to fetch or parse RSS feed", rss_url=rss_url, error=str(e))
            return []

    async def extract_full_content(self, url: str) -> str:
        """
        Launches an async headless browser context via Playwright, navigates to the URL,
        waits for DOM content hydration, and parses the clean body text using BeautifulSoup.
        """
        logger.info("Launching Playwright for article extraction", url=url)
        async with async_playwright() as p:
            # Launch headless browser
            browser = await p.chromium.launch(headless=True)
            try:
                # Setup browser context with realistic User-Agent
                user_agent = (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
                context = await browser.new_context(user_agent=user_agent)
                page = await context.new_page()
                
                # Navigate and wait for DOM Content Loaded
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                
                # Retrieve fully hydrated HTML content
                html = await page.content()
                
                # Parse with BeautifulSoup
                soup = BeautifulSoup(html, "html.parser")
                
                # Clean HTML document of typical metadata/script junk
                for junk_tag in soup(["script", "style", "form", "header", "footer", "nav", "aside", "iframe"]):
                    junk_tag.decompose()
                    
                # Collect body paragraph contents
                paragraphs = soup.find_all("p")
                text_blocks = []
                for p_tag in paragraphs:
                    text = p_tag.get_text(strip=True)
                    # Filter out short fragments (cookies notices, newsletter signups, read-more links)
                    if len(text) > 30:
                        text_blocks.append(text)
                        
                extracted_content = "\n\n".join(text_blocks)

                rejection = self._reject_if_blocked(extracted_content, url)
                if rejection:
                    logger.warn("Rejected non-article page", url=url, reason=rejection)
                    return ""

                logger.info("Playwright content extraction success", url=url, size_chars=len(extracted_content))
                return extracted_content
            except Exception as e:
                logger.error("Playwright content extraction failed", url=url, error=str(e))
                raise e
            finally:
                await browser.close()

    async def run_pipeline(self) -> None:
        """
        Runs the full hybrid scraping pipeline: discovers new links, checks duplicates,
        runs browser-based extraction, and inserts new articles into the database.
        """
        logger.info("Starting ingestion scraper pipeline execution")
        
        # Spin up dedicated session for background task
        async with AsyncSessionFactory() as session:
            try:
                # 1. Fetch active Sources from DB
                res = await session.execute(select(Source))
                sources_db = res.scalars().all()
                sources = [
                    {"id": s.id, "name": s.name, "url": s.url}
                    for s in sources_db
                ]
                logger.info("Found media sources for sync", count=len(sources))
                
                repo = ArticleRepository(session)
                
                for source in sources:
                    rss_url = self._resolve_rss_url(source["name"], source["url"])
                    logger.info("Syncing source feed", source_name=source["name"], rss_url=rss_url)
                    
                    # 2. Discover articles from RSS feed
                    rss_articles = await self.fetch_rss_links(rss_url)
                    
                    for item in rss_articles:
                        url = item["url"]
                        
                        try:
                            # 3. Fast idempotency pre-check to prevent starting browser for duplicates
                            stmt = select(Article).where(Article.url == url)
                            check_res = await session.execute(stmt)
                            if check_res.scalars().first():
                                logger.debug("Skipping duplicate article url", url=url)
                                continue
                                
                            # 4. Perform Playwright Browser extraction
                            content = await self.extract_full_content(url)
                            if not content.strip():
                                logger.warn("Scraped article text is empty, skipping insertion", url=url)
                                continue
                                
                            # 5. Insert new article into database
                            article_data = {
                                "title": item["title"],
                                "url": url,
                                "published_at": item["published_at"],
                                "content": content,
                                "source_id": str(source["id"])
                            }
                            
                            new_art = await repo.create_scraped_article(article_data)
                            if new_art:
                                logger.info(
                                    "Saved new article to database",
                                    id=str(new_art.id),
                                    title=new_art.title,
                                    url=new_art.url
                                )
                            else:
                                logger.info("Duplicate article dropped during insert", url=url)
                                
                        except Exception as entry_err:
                            logger.exception(
                                "Failed to process article entry in pipeline",
                                url=url
                            )
                            # Rollback session to clear failed transaction state
                            await session.rollback()
                            continue
                            
                logger.info("Ingestion scraper pipeline completed successfully")
            except Exception as e:
                logger.exception("Scraper pipeline encountered a fatal execution failure")
                await session.rollback()
