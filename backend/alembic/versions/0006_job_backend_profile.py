"""job backend_profile snapshot

Stores an enqueue-time deep copy of the chosen Settings.profiles entry
(backend fields) + whisper_model/whisper_device from Settings. The worker
reads job config from here, never from global Settings, so a later profile
edit/delete cannot corrupt a queued job.

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-16 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("backend_profile", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "backend_profile")
