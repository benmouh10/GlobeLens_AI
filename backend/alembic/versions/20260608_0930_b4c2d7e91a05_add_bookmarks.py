"""add_bookmarks

Adds the bookmarks table backing the reading-list feature. The Bookmark model
was added to app.entities.models without a matching revision, so the endpoint
failed with UndefinedTableError on first call.

Both foreign keys cascade. articles.event_id uses SET NULL, which is why
deleting an article earlier left empty Event rows behind; a bookmark is a
user-created record with no value without its event, so removing the event
should remove the bookmark too.

The unique constraint on (user_id, event_id) is what makes bookmarking
idempotent. The endpoint already checks for an existing row, but a check plus
insert races two concurrent requests and produces duplicates; the constraint
turns that race into a no-op instead.

Revision ID: b4c2d7e91a05
Revises: c3a91d5e7b24
Create Date: 2026-06-08 09:30:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b4c2d7e91a05'
down_revision: Union[str, None] = 'c3a91d5e7b24'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS bookmarks (
            id UUID NOT NULL,
            user_id UUID NOT NULL,
            event_id UUID NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT bookmarks_pkey PRIMARY KEY (id),
            CONSTRAINT bookmarks_user_id_event_id_key UNIQUE (user_id, event_id),
            CONSTRAINT bookmarks_user_id_fkey FOREIGN KEY (user_id)
                REFERENCES users(id) ON DELETE CASCADE,
            CONSTRAINT bookmarks_event_id_fkey FOREIGN KEY (event_id)
                REFERENCES events(id) ON DELETE CASCADE
        );
        """
    )
    # Two lookups dominate: "this user's bookmarks, newest first" and
    # "is this event already saved". The unique constraint covers the second
    # as a prefix index; the first needs user_id leading for the sort.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bookmarks_user_id_created_at "
        "ON bookmarks (user_id, created_at DESC);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bookmarks_event_id ON bookmarks (event_id);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS bookmarks;")