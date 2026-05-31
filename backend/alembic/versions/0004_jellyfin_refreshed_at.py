"""add jellyfin_refreshed_at column to jobs

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-06 21:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'jobs',
        sa.Column('jellyfin_refreshed_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('jobs', 'jellyfin_refreshed_at')
