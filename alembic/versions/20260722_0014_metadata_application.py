"""Add canonical metadata application audit state.

Revision ID: 20260722_0014
Revises: 20260722_0013
"""
from alembic import op
import sqlalchemy as sa

revision = "20260722_0014"
down_revision = "20260722_0013"
branch_labels = None
depends_on = None

def upgrade() -> None:
    with op.batch_alter_table("songs") as batch:
        batch.add_column(sa.Column("musicbrainz_release_group_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("musicbrainz_release_artist_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("release_date", sa.String(10), nullable=True))
        batch.add_column(sa.Column("original_release_date", sa.String(10), nullable=True))
        batch.create_index("ix_songs_musicbrainz_release_group_id", ["musicbrainz_release_group_id"])
        batch.create_index("ix_songs_musicbrainz_release_artist_id", ["musicbrainz_release_artist_id"])
    op.create_table("metadata_application_batches", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("entity_scope", sa.String(40), nullable=False), sa.Column("status", sa.String(40), nullable=False), sa.Column("total_fields", sa.Integer(), nullable=False), sa.Column("applied_fields", sa.Integer(), nullable=False), sa.Column("unchanged_fields", sa.Integer(), nullable=False), sa.Column("stale_fields", sa.Integer(), nullable=False), sa.Column("invalid_fields", sa.Integer(), nullable=False), sa.Column("unsupported_fields", sa.Integer(), nullable=False), sa.Column("failed_fields", sa.Integer(), nullable=False), sa.Column("forced_fields", sa.Integer(), nullable=False), sa.Column("initiated_by", sa.String(120)), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("started_at", sa.DateTime()), sa.Column("completed_at", sa.DateTime()), sa.Column("job_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="SET NULL")), sa.Column("error_metadata", sa.Text()))
    op.create_index("ix_metadata_application_batches_status_created", "metadata_application_batches", ["status", "created_at"])
    with op.batch_alter_table("metadata_history") as batch:
        # SQLite batch operations require named constraints.  These nullable
        # audit references are indexed but intentionally unconstrained so old
        # retained history remains migration-safe.
        batch.add_column(sa.Column("suggestion_id", sa.Integer()))
        batch.add_column(sa.Column("discovery_id", sa.Integer()))
        batch.add_column(sa.Column("match_result_id", sa.Integer()))
        batch.add_column(sa.Column("application_batch_id", sa.Integer()))
        batch.add_column(sa.Column("forced", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("stale_override_reason", sa.String(500)))
        batch.create_index("ix_metadata_history_suggestion_id", ["suggestion_id"])
        batch.create_index("ix_metadata_history_discovery_id", ["discovery_id"])
        batch.create_index("ix_metadata_history_match_result_id", ["match_result_id"])
        batch.create_index("ix_metadata_history_application_batch_id", ["application_batch_id"])

def downgrade() -> None:
    with op.batch_alter_table("metadata_history") as batch:
        for name in ("ix_metadata_history_application_batch_id", "ix_metadata_history_match_result_id", "ix_metadata_history_discovery_id", "ix_metadata_history_suggestion_id"): batch.drop_index(name)
        for name in ("stale_override_reason", "forced", "application_batch_id", "match_result_id", "discovery_id", "suggestion_id"): batch.drop_column(name)
    op.drop_table("metadata_application_batches")
    with op.batch_alter_table("songs") as batch:
        batch.drop_index("ix_songs_musicbrainz_release_artist_id"); batch.drop_index("ix_songs_musicbrainz_release_group_id")
        for name in ("original_release_date", "release_date", "musicbrainz_release_artist_id", "musicbrainz_release_group_id"): batch.drop_column(name)
