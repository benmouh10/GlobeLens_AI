"""add event_contradictions table

Records disagreements between outlets covering the same event. Detection
lives in app/services/contradiction_service.py.

Revision ID: d7e2f10a94bc
Revises: b4c2d7e91a05
Create Date: 2026-06-09 1140
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "d7e2f10a94bc"
down_revision: Union[str, None] = "b4c2d7e91a05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "event_contradictions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=sa.func.gen_random_uuid()),
        sa.Column("event_id", UUID(as_uuid=True), nullable=False),
        sa.Column("nature", sa.String(length=50), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("claim_a_text", sa.Text(), nullable=False),
        sa.Column("claim_a_source", sa.String(length=255), nullable=False),
        sa.Column("claim_b_text", sa.Text(), nullable=False),
        sa.Column("claim_b_source", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            ondelete="CASCADE",
        ),
        # Re-scanning an unchanged event must not accumulate duplicates.
        sa.UniqueConstraint(
            "event_id",
            "nature",
            "claim_a_text",
            "claim_b_text",
            name="uq_event_contradiction_pair",
        ),
    )
    op.create_index(
        "ix_event_contradictions_event_id",
        "event_contradictions",
        ["event_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_event_contradictions_event_id", table_name="event_contradictions")
    op.drop_table("event_contradictions")