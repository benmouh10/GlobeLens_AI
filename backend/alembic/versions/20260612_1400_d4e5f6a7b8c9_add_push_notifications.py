"""add push notifications

Creates push_subscriptions (one row per browser/device endpoint) and
push_preferences (one row per user, category opt-ins).

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-12 1400
"""
from typing import Sequence, Union

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id UUID NOT NULL,
            user_id UUID NOT NULL,
            endpoint TEXT NOT NULL,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            user_agent TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_used_at TIMESTAMPTZ,
            CONSTRAINT push_subscriptions_pkey PRIMARY KEY (id),
            CONSTRAINT push_subscriptions_endpoint_key UNIQUE (endpoint),
            CONSTRAINT push_subscriptions_user_id_fkey FOREIGN KEY (user_id)
                REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_push_subscriptions_user_id "
        "ON push_subscriptions (user_id);"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS push_preferences (
            id UUID NOT NULL,
            user_id UUID NOT NULL,
            breaking_news BOOLEAN NOT NULL DEFAULT true,
            followed_events BOOLEAN NOT NULL DEFAULT true,
            daily_briefing BOOLEAN NOT NULL DEFAULT false,
            briefing_hour_utc INTEGER NOT NULL DEFAULT 8,
            timezone VARCHAR(64) NOT NULL DEFAULT 'UTC',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT push_preferences_pkey PRIMARY KEY (id),
            CONSTRAINT push_preferences_user_id_key UNIQUE (user_id),
            CONSTRAINT push_preferences_user_id_fkey FOREIGN KEY (user_id)
                REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS push_preferences;")
    op.execute("DROP TABLE IF EXISTS push_subscriptions;")
