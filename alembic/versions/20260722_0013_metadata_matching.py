"""Add durable provider-neutral metadata discoveries and ranked results.

Revision ID: 20260722_0013
Revises: 20260722_0012
"""

from alembic import op
import sqlalchemy as sa

revision = "20260722_0013"
down_revision = "20260722_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    suggestion_columns = {
        column["name"] for column in inspector.get_columns("metadata_suggestions")
    }
    suggestion_indexes = {
        index["name"] for index in inspector.get_indexes("metadata_suggestions")
    }
    with op.batch_alter_table("metadata_suggestions") as batch:
        if "discovery_id" not in suggestion_columns:
            batch.add_column(sa.Column("discovery_id", sa.Integer(), nullable=True))
        if "match_result_id" not in suggestion_columns:
            batch.add_column(sa.Column("match_result_id", sa.Integer(), nullable=True))
        if "ix_metadata_suggestions_discovery_id" not in suggestion_indexes:
            batch.create_index("ix_metadata_suggestions_discovery_id", ["discovery_id"])
        if "ix_metadata_suggestions_match_result_id" not in suggestion_indexes:
            batch.create_index(
                "ix_metadata_suggestions_match_result_id", ["match_result_id"]
            )
    if "metadata_discoveries" not in inspector.get_table_names():
        op.create_table(
            "metadata_discoveries",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("entity_type", sa.String(20), nullable=False),
            sa.Column("entity_id", sa.String(500), nullable=False),
            sa.Column("provider", sa.String(80), nullable=False),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("selected_match_result_id", sa.Integer(), nullable=True),
            sa.Column("ambiguous", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime()),
            sa.Column(
                "job_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="SET NULL")
            ),
            sa.Column("matcher_version", sa.String(80), nullable=False),
            sa.Column("scoring_version", sa.String(80), nullable=False),
            sa.Column("query_summary", sa.Text()),
            sa.Column("error_metadata", sa.Text()),
            sa.Column("canonical_snapshot_hash", sa.String(64)),
            sa.CheckConstraint(
                "entity_type IN ('song', 'album', 'artist')",
                name="ck_metadata_discovery_entity_type",
            ),
            sa.CheckConstraint(
                "status IN ('queued', 'running', 'completed', 'completed_with_errors', 'cancelled', 'failed')",
                name="ck_metadata_discovery_status",
            ),
        )
    discovery_indexes = {
        index["name"] for index in sa.inspect(bind).get_indexes("metadata_discoveries")
    }
    for name, columns in (
        ("ix_metadata_discoveries_entity", ["entity_type", "entity_id", "created_at"]),
        ("ix_metadata_discoveries_filter", ["provider", "status", "ambiguous"]),
        ("ix_metadata_discoveries_job", ["job_id"]),
        (
            "ix_metadata_discoveries_selected_match_result_id",
            ["selected_match_result_id"],
        ),
        ("ix_metadata_discoveries_ambiguous", ["ambiguous"]),
        ("ix_metadata_discoveries_created_at", ["created_at"]),
    ):
        if name not in discovery_indexes:
            op.create_index(name, "metadata_discoveries", columns)
    if "metadata_match_results" not in inspector.get_table_names():
        op.create_table(
            "metadata_match_results",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "discovery_id",
                sa.Integer(),
                sa.ForeignKey("metadata_discoveries.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("provider_entity_id", sa.String(255), nullable=False),
            sa.Column("rank", sa.Integer(), nullable=False),
            sa.Column("score", sa.Float(), nullable=False),
            sa.Column("confidence_level", sa.String(20), nullable=False),
            sa.Column("viable", sa.Boolean(), nullable=False),
            sa.Column("ambiguous", sa.Boolean(), nullable=False),
            sa.Column("hard_rejection", sa.Boolean(), nullable=False),
            sa.Column("candidate_summary", sa.Text(), nullable=False),
            sa.Column("positive_evidence", sa.Text(), nullable=False),
            sa.Column("conflicting_evidence", sa.Text(), nullable=False),
            sa.Column("unavailable_evidence", sa.Text(), nullable=False),
            sa.Column("rejection_reasons", sa.Text(), nullable=False),
            sa.Column("search_provenance", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint(
                "confidence_level IN ('exact', 'high', 'medium', 'low', 'rejected')",
                name="ck_metadata_match_confidence",
            ),
            sa.CheckConstraint(
                "score >= 0 AND score <= 100", name="ck_metadata_match_score"
            ),
        )
    result_indexes = {
        index["name"]
        for index in sa.inspect(bind).get_indexes("metadata_match_results")
    }
    for name, columns, unique in (
        ("ix_metadata_match_results_ranking", ["discovery_id", "rank", "score"], False),
        ("ix_metadata_match_results_confidence", ["confidence_level", "score"], False),
        (
            "uq_metadata_match_result_provider",
            ["discovery_id", "provider_entity_id"],
            True,
        ),
        ("ix_metadata_match_results_created_at", ["created_at"], False),
    ):
        if name not in result_indexes:
            op.create_index(name, "metadata_match_results", columns, unique=unique)
    if "metadata_discovery_locks" not in inspector.get_table_names():
        op.create_table(
            "metadata_discovery_locks",
            sa.Column("song_id", sa.Integer(), primary_key=True),
            sa.Column(
                "task_id",
                sa.Integer(),
                sa.ForeignKey("tasks.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    lock_indexes = {
        index["name"]
        for index in sa.inspect(bind).get_indexes("metadata_discovery_locks")
    }
    if "ix_metadata_discovery_locks_task_id" not in lock_indexes:
        op.create_index(
            "ix_metadata_discovery_locks_task_id",
            "metadata_discovery_locks",
            ["task_id"],
        )


def downgrade() -> None:
    op.drop_table("metadata_discovery_locks")
    op.drop_table("metadata_match_results")
    op.drop_table("metadata_discoveries")
    with op.batch_alter_table("metadata_suggestions") as batch:
        batch.drop_index("ix_metadata_suggestions_match_result_id")
        batch.drop_index("ix_metadata_suggestions_discovery_id")
        batch.drop_column("match_result_id")
        batch.drop_column("discovery_id")
