"""jobs.source_srt_path: start the pipeline from an existing SRT.

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-14

Set by the auto-retry fast path (translation-only verification fails
re-translate from the original run's source SRT instead of re-transcribing)
and later by the existing-subtitles gate. NULL = normal ASR pipeline.
"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("source_srt_path", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "source_srt_path")
