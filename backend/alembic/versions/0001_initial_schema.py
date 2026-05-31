"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-24 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'jobs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('phase', sa.String(), nullable=True),
        sa.Column('progress', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('file_path', sa.String(), nullable=False),
        sa.Column('source_language', sa.String(), nullable=True),
        sa.Column('target_language', sa.String(), nullable=True),
        sa.Column('model_size', sa.String(), nullable=True),
        sa.Column('log_path', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nas_mount_path', sa.String(), nullable=True),
        sa.Column('jellyfin_url', sa.String(), nullable=True),
        sa.Column('jellyfin_api_key', sa.String(), nullable=True),
        sa.Column('default_model_size', sa.String(), nullable=False, server_default='large-v3'),
        sa.Column('translation_provider', sa.String(), nullable=True),
        sa.Column('translation_model', sa.String(), nullable=True),
        sa.Column('translation_api_key', sa.String(), nullable=True),
        sa.Column('translation_base_url', sa.String(), nullable=True),
        sa.Column('huggingface_token', sa.String(), nullable=True),
        sa.Column('watch_folders', JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('settings')
    op.drop_table('jobs')
