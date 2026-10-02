"""add authored articles (author_id, origin, publication_status)

Lets journalists write their own articles in the newsroom, alongside the ones
the scraper collects. Existing rows stay origin=PIPELINE / PUBLISHED; authored
rows carry an author_id and start as DRAFT. Authored articles have no publisher
URL, so articles.url becomes nullable.

Revision ID: f1a2b3c4d5e6
Revises: d7e2f10a94bc
Create Date: 2026-06-10 1200
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ENUM


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "d7e2f10a94bc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# create_type=False: add_column does not emit CREATE TYPE, so the types are
# created once, explicitly, before the columns that use them.
ARTICLE_ORIGIN = ENUM("PIPELINE", "AUTHORED", name="articleorigin", create_type=False)
PUBLICATION_STATUS = ENUM("DRAFT", "PUBLISHED", name="publicationstatus", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    ARTICLE_ORIGIN.create(bind, checkfirst=True)
    PUBLICATION_STATUS.create(bind, checkfirst=True)

    op.add_column(
        "articles",
        sa.Column("origin", ARTICLE_ORIGIN, nullable=False, server_default="PIPELINE"),
    )
    op.add_column(
        "articles",
        sa.Column(
            "publication_status",
            PUBLICATION_STATUS,
            nullable=False,
            server_default="PUBLISHED",
        ),
    )
    op.add_column("articles", sa.Column("author_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_articles_author_id_users",
        "articles",
        "users",
        ["author_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_articles_author_id", "articles", ["author_id"])
    op.create_index("ix_articles_origin", "articles", ["origin"])
    op.create_index("ix_articles_publication_status", "articles", ["publication_status"])

    # Authored articles have no publisher URL. The unique constraint stays;
    # PostgreSQL treats multiple NULLs as distinct.
    op.alter_column(
        "articles", "url", existing_type=sa.String(length=2000), nullable=True
    )


def downgrade() -> None:
    op.alter_column(
        "articles", "url", existing_type=sa.String(length=2000), nullable=False
    )
    op.drop_index("ix_articles_publication_status", table_name="articles")
    op.drop_index("ix_articles_origin", table_name="articles")
    op.drop_index("ix_articles_author_id", table_name="articles")
    op.drop_constraint("fk_articles_author_id_users", "articles", type_="foreignkey")
    op.drop_column("articles", "author_id")
    op.drop_column("articles", "publication_status")
    op.drop_column("articles", "origin")
    # drop_column does not remove the enum types.
    ENUM(name="publicationstatus").drop(op.get_bind(), checkfirst=True)
    ENUM(name="articleorigin").drop(op.get_bind(), checkfirst=True)
