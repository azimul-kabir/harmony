"""Add normalized metadata provider cache.

Revision ID: 20260722_0012
Revises: 20260722_0011
"""
from alembic import op
import sqlalchemy as sa

revision = "20260722_0012"
down_revision = "20260722_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_cache_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("cache_key", sa.String(64), nullable=False),
        sa.Column("lookup_type", sa.String(40), nullable=False),
        sa.Column("query", sa.String(1000), nullable=True),
        sa.Column("entity_id", sa.String(255), nullable=True),
        sa.Column("normalized_data", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("provider_version", sa.String(40), nullable=False),
    )
    op.create_index("uq_provider_cache_key", "provider_cache_entries", ["provider", "cache_key"], unique=True)
    op.create_index("ix_provider_cache_expiry", "provider_cache_entries", ["provider", "expires_at"])


def downgrade() -> None:
    op.drop_table("provider_cache_entries")
