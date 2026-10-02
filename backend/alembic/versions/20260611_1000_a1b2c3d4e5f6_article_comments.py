"""allow comments on newsroom-authored articles

Dispatches written in the newsroom are not attached to an aggregated Event, so
their discussion needs its own anchor. A comment now targets either an Event or
an Article: event_id becomes nullable, article_id is added, and a check
constraint keeps exactly one of the two set on every row.

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-06-11 1000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("comments", "event_id", existing_type=UUID(as_uuid=True), nullable=True)
    op.add_column("comments", sa.Column("article_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_comments_article_id_articles",
        "comments",
        "articles",
        ["article_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_comments_article_id", "comments", ["article_id"])
    op.create_check_constraint(
        "ck_comment_exactly_one_target",
        "comments",
        "(event_id IS NOT NULL) <> (article_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_comment_exactly_one_target", "comments", type_="check")
    op.drop_index("ix_comments_article_id", table_name="comments")
    op.drop_constraint("fk_comments_article_id_articles", "comments", type_="foreignkey")
    op.drop_column("comments", "article_id")
    # Drop article comments before restoring the NOT NULL event_id constraint.
    op.execute("DELETE FROM comments WHERE event_id IS NULL")
    op.alter_column("comments", "event_id", existing_type=UUID(as_uuid=True), nullable=False)
