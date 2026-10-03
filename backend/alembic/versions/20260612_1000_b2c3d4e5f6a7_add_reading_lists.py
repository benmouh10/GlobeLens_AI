"""add reading lists

Adds named, ordered collections of saved events/articles on top of the flat
bookmarks table. reading_list_items mirrors comments: exactly one of event_id /
article_id is set, enforced by a check constraint, and both foreign keys cascade
so a removed event or article does not leave a dangling list entry.

The unique constraints make adds idempotent at the database level. A unique
constraint on (list_id, event_id) does not constrain article rows: PostgreSQL
treats NULLs as distinct, so many article rows (event_id NULL) coexist while an
event can only appear once per list.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-12 1000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS reading_lists (
            id UUID NOT NULL,
            user_id UUID NOT NULL,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            is_public BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT reading_lists_pkey PRIMARY KEY (id),
            CONSTRAINT uq_reading_list_user_name UNIQUE (user_id, name),
            CONSTRAINT reading_lists_user_id_fkey FOREIGN KEY (user_id)
                REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_reading_lists_user_id ON reading_lists (user_id);"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS reading_list_items (
            id UUID NOT NULL,
            list_id UUID NOT NULL,
            event_id UUID,
            article_id UUID,
            position INTEGER NOT NULL DEFAULT 0,
            note TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT reading_list_items_pkey PRIMARY KEY (id),
            CONSTRAINT ck_reading_list_item_exactly_one_target CHECK (
                (event_id IS NOT NULL) <> (article_id IS NOT NULL)
            ),
            CONSTRAINT uq_reading_list_item_event UNIQUE (list_id, event_id),
            CONSTRAINT uq_reading_list_item_article UNIQUE (list_id, article_id),
            CONSTRAINT reading_list_items_list_id_fkey FOREIGN KEY (list_id)
                REFERENCES reading_lists(id) ON DELETE CASCADE,
            CONSTRAINT reading_list_items_event_id_fkey FOREIGN KEY (event_id)
                REFERENCES events(id) ON DELETE CASCADE,
            CONSTRAINT reading_list_items_article_id_fkey FOREIGN KEY (article_id)
                REFERENCES articles(id) ON DELETE CASCADE
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_reading_list_items_list_id_position "
        "ON reading_list_items (list_id, position);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_reading_list_items_event_id ON reading_list_items (event_id);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_reading_list_items_article_id ON reading_list_items (article_id);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reading_list_items;")
    op.execute("DROP TABLE IF EXISTS reading_lists;")
