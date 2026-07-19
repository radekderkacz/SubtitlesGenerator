"""Existing-subtitles preference: global toggle + per-job resolved flag.

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-14

- settings.prefer_existing_subs (default true): when a video ships with a
  text subtitle track (sidecar or embedded) that passes verification, use
  it as the translation source instead of transcribing.
- jobs.use_existing_subs: the enqueue-time resolution of that preference
  (payload override wins, else the global toggle), so a later settings
  flip can't change a queued job's behavior.
"""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "settings",
        sa.Column("prefer_existing_subs", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
    )
    op.add_column(
        "jobs",
        sa.Column("use_existing_subs", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("jobs", "use_existing_subs")
    op.drop_column("settings", "prefer_existing_subs")
