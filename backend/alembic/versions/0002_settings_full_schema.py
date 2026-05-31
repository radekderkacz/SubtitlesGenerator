"""settings full schema

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rename columns to match canonical schema
    op.alter_column('settings', 'default_model_size', new_column_name='whisper_model')
    op.alter_column('settings', 'translation_base_url', new_column_name='translation_api_url')
    op.alter_column('settings', 'huggingface_token', new_column_name='hf_token')

    # Set server defaults on renamed / existing columns
    op.alter_column(
        'settings', 'nas_mount_path',
        server_default='/media',
    )
    op.alter_column(
        'settings', 'whisper_model',
        server_default='large-v3',
    )
    op.alter_column(
        'settings', 'watch_folders',
        server_default=sa.text("'[]'::json"),
    )

    # Add new columns
    op.add_column('settings', sa.Column('transcription_backend', sa.String(), nullable=True))
    op.add_column('settings', sa.Column('whisper_device', sa.String(), nullable=True,
                                        server_default='auto'))
    op.add_column('settings', sa.Column('transcription_api_url', sa.String(), nullable=True))
    op.add_column('settings', sa.Column('transcription_model', sa.String(), nullable=True))
    op.add_column('settings', sa.Column('transcription_api_key', sa.String(), nullable=True))


def downgrade() -> None:
    # Drop new columns
    op.drop_column('settings', 'transcription_api_key')
    op.drop_column('settings', 'transcription_model')
    op.drop_column('settings', 'transcription_api_url')
    op.drop_column('settings', 'whisper_device')
    op.drop_column('settings', 'transcription_backend')

    # Remove server defaults added in upgrade
    op.alter_column('settings', 'watch_folders', server_default=None)
    op.alter_column('settings', 'nas_mount_path', server_default=None)

    # Rename columns back to original names
    op.alter_column('settings', 'hf_token', new_column_name='huggingface_token')
    op.alter_column('settings', 'translation_api_url', new_column_name='translation_base_url')
    op.alter_column('settings', 'whisper_model', new_column_name='default_model_size')
