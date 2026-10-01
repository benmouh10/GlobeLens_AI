"""
One-off: delete stored articles that are bot-detection stubs.

Three CNN articles were stored whose entire body is the app-download
interstitial ("Scan the QR code to download the CNN app on Google Play"),
exactly 120 characters. The scraper now rejects them via BLOCK_PAGE_SIGNATURES,
but these predate that guard. Enriching them produced summaries such as "The
article is a placeholder for a QR code document", which describes the scrape
rather than the news.

Only whole-body matches count. An earlier version matched the signature
anywhere in the text and destroyed 10 legitimate articles, because BBC, DW and
France24 pages carry a QR-code or "download the app" link in a footer while
the article body above it is real. That mistake was invisible because the
script printed its deletes and exited 0. Hence --plan below.

    python -m app.purge_stubs --plan     # report only, changes nothing
    python -m app.purge_stubs            # delete

Deleting an article leaves its event in place; rerun recluster if the event
should be re-derived from the remaining articles.
"""
import argparse
import asyncio

from sqlalchemy import delete, select

from app.core.database import AsyncSessionFactory
from app.entities.models import Article, Embedding

STUB_SIGNATURES = ("scan the qr code to download", "download the cnn app")
STUB_MAX_CHARS = 200

# A stub signature appearing on more than this share of stored articles means
# the guard is matching something common, not an interstitial. 121 articles
# with 3 stubs is ~2.5%; the footer-link version hit 10% and was wrong.
MAX_MATCH_RATE = 0.05


def find_stubs(articles: list[Article]) -> list[Article]:
    doomed = []
    for article in articles:
        content = (article.content or "").strip()
        if len(content) > STUB_MAX_CHARS:
            continue
        if any(sig in content.lower() for sig in STUB_SIGNATURES):
            doomed.append(article)
    return doomed


def report(articles: list[Article], doomed: list[Article]) -> bool:
    """Print the plan. Returns True when it looks safe to proceed."""
    total = len(articles)
    rate = len(doomed) / total if total else 0.0
    print(f"corpus: {total} articles")
    print(f"would delete {len(doomed)} ({rate:.1%})")
    for article in doomed:
        body = (article.content or "").strip()
        print(f"  {str(article.id)[:8]} | {len(body):>5} chars | {article.title[:60]}")

    if not doomed:
        print("\nnothing to do.")
        return True

    if rate > MAX_MATCH_RATE:
        print(
            f"\nABORT: {rate:.1%} of the corpus matches, above the "
            f"{MAX_MATCH_RATE:.0%} threshold. A stub guard should hit a "
            f"tiny fraction; this is matching common page furniture."
        )
        return False

    print("\nsafe by rate. rerun without --plan to delete.")
    return True


async def main(plan_only: bool) -> None:
    async with AsyncSessionFactory() as session:
        articles = (await session.execute(select(Article))).scalars().all()
        doomed = find_stubs(articles)

        if plan_only:
            report(articles, doomed)
            return

        if not report(articles, doomed):
            return

        for article in doomed:
            # Delete the embedding first. The FK is ON DELETE CASCADE in the
            # database, but the ORM relationship was not loaded, so
            # session.delete() tried to null the column and hit the NOT NULL
            # constraint on embeddings.article_id.
            await session.execute(
                delete(Embedding).where(Embedding.article_id == article.id)
            )
            await session.delete(article)
        await session.commit()
        print(f"\ndeleted {len(doomed)} stub articles")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan",
        action="store_true",
        help="report what would be deleted and change nothing",
    )
    args = parser.parse_args()
    asyncio.run(main(args.plan))