"""Add playlist_import_batches table

Revision ID: 1f8d82846508
Revises: 20260725_0026
Create Date: 2026-07-25 08:26:30.048726
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '1f8d82846508'
down_revision: Union[str, Sequence[str], None] = '20260725_0026'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table('playlist_import_batches',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('task_id', sa.Integer(), nullable=False),
    sa.Column('playlist_id', sa.Integer(), nullable=False),
    sa.Column('batch_number', sa.Integer(), nullable=False),
    sa.Column('start_position', sa.Integer(), nullable=False),
    sa.Column('end_position', sa.Integer(), nullable=False),
    sa.Column('discovered_count', sa.Integer(), nullable=False, default=0),
    sa.Column('queued_count', sa.Integer(), nullable=False, default=0),
    sa.Column('skipped_count', sa.Integer(), nullable=False, default=0),
    sa.Column('status', sa.String(), nullable=False, default="pending"),
    sa.Column('error_summary', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['playlist_id'], ['playlists.id'], ),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('task_id', 'batch_number', name='uix_task_batch')
    )
    op.create_index(op.f('ix_playlist_import_batches_playlist_id'), 'playlist_import_batches', ['playlist_id'], unique=False)
    op.create_index(op.f('ix_playlist_import_batches_task_id'), 'playlist_import_batches', ['task_id'], unique=False)

def downgrade() -> None:
    op.drop_index(op.f('ix_playlist_import_batches_task_id'), table_name='playlist_import_batches')
    op.drop_index(op.f('ix_playlist_import_batches_playlist_id'), table_name='playlist_import_batches')
    op.drop_table('playlist_import_batches')
