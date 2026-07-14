"""Idempotency layer: one active job per file + trigger fire stamps.

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-07

- Partial unique index on jobs(file_path) for active (queued/processing)
  rows: concurrent submissions of the same file — watcher + manual + cron
  racing — collapse to one job at the database level instead of relying on
  check-then-act reads.
- triggers.last_fired_at: cron evaluation previously derived the last fire
  from TriggerEvent rows, so a scan that dispatched nothing left no trace
  and the trigger re-fired (and re-walked the NAS) every minute forever.
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_jobs_active_file",
        "jobs",
        ["file_path"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'processing')"),
    )
    op.add_column(
        "triggers",
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("triggers", "last_fired_at")
    op.drop_index("uq_jobs_active_file", table_name="jobs")
