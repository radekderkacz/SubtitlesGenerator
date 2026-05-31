"""Automations UX redesign — wipe triggers; rules -> action + file_filter.

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-21

Wipe-and-recreate: all triggers + trigger_events are DELETED (the UX redesign
changes the trigger shape; a 1-shipped-day-ago feature with only test data).
Downgrade restores the `rules` column shape but NOT the deleted rows.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM trigger_events")
    op.execute("DELETE FROM triggers")
    op.drop_column("triggers", "rules")
    op.add_column("triggers", sa.Column("action", JSONB(), nullable=True))
    op.add_column("triggers", sa.Column("file_filter", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("triggers", "file_filter")
    op.drop_column("triggers", "action")
    op.add_column("triggers", sa.Column(
        "rules", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
