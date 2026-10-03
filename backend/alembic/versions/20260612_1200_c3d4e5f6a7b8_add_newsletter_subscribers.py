"""add newsletter subscribers

Creates the newsletter_subscribers table backing the digest feature. Kept
separate from users because most subscribers are anonymous readers; user_id is
nullable and ON DELETE SET NULL so removing an account does not silently drop
the subscription.

Both tokens are unique. confirm_token is nullable: an unsubscribe id must exist
for every row (including ones created before confirmation), while a confirmation
id only exists while the address is unconfirmed.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-12 1200
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS newsletter_subscribers (
            id UUID NOT NULL,
            email VARCHAR(320) NOT NULL,
            user_id UUID,
            interests VARCHAR[] DEFAULT '{}',
            frequency VARCHAR(20) NOT NULL DEFAULT 'daily',
            is_active BOOLEAN NOT NULL DEFAULT true,
            is_confirmed BOOLEAN NOT NULL DEFAULT false,
            confirm_token VARCHAR(64),
            unsubscribe_token VARCHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            confirmed_at TIMESTAMPTZ,
            last_sent_at TIMESTAMPTZ,
            unsubscribed_at TIMESTAMPTZ,
            CONSTRAINT newsletter_subscribers_pkey PRIMARY KEY (id),
            CONSTRAINT newsletter_subscribers_email_key UNIQUE (email),
            CONSTRAINT newsletter_subscribers_confirm_token_key UNIQUE (confirm_token),
            CONSTRAINT newsletter_subscribers_unsubscribe_token_key UNIQUE (unsubscribe_token),
            CONSTRAINT newsletter_subscribers_user_id_fkey FOREIGN KEY (user_id)
                REFERENCES users(id) ON DELETE SET NULL
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_newsletter_subscribers_email "
        "ON newsletter_subscribers (email);"
    )
    # The dispatch query is "active + confirmed subscribers for a cadence".
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_newsletter_subscribers_dispatch "
        "ON newsletter_subscribers (frequency, is_active, is_confirmed);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS newsletter_subscribers;")
