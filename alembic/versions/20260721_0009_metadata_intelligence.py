"""Add provider-neutral metadata suggestions and history."""
from alembic import op
import sqlalchemy as sa

revision = "20260721_0009"
down_revision = "20260721_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "metadata_suggestions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entity_type", sa.String(20), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("field_name", sa.String(80), nullable=False),
        sa.Column("current_value", sa.Text()), sa.Column("suggested_value", sa.Text()),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("provider_entity_id", sa.String(255)),
        sa.Column("confidence", sa.Float()),
        sa.Column("confidence_level", sa.String(20), nullable=False),
        sa.Column("match_explanation", sa.String(1000)),
        sa.Column("positive_evidence", sa.Text()), sa.Column("conflicting_evidence", sa.Text()),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime()), sa.Column("applied_at", sa.DateTime()),
        sa.Column("rejected_at", sa.DateTime()),
        sa.Column("created_by_job_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="SET NULL")),
        sa.Column("reviewed_by", sa.String(120)),
        sa.CheckConstraint("entity_type IN ('song', 'album', 'artist')", name="ck_metadata_suggestion_entity_type"),
        sa.CheckConstraint("status IN ('pending', 'accepted', 'rejected', 'superseded', 'applied', 'apply_failed')", name="ck_metadata_suggestion_status"),
        sa.CheckConstraint("confidence_level IN ('exact', 'high', 'medium', 'low', 'rejected')", name="ck_metadata_suggestion_confidence_level"),
        sa.CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_metadata_suggestion_confidence"),
    )
    op.create_index("ix_metadata_suggestions_entity", "metadata_suggestions", ["entity_type", "entity_id", "field_name"])
    op.create_index("ix_metadata_suggestions_pending", "metadata_suggestions", ["status", "created_at"])
    op.create_index("ix_metadata_suggestions_provider", "metadata_suggestions", ["provider"])
    op.create_index("ix_metadata_suggestions_confidence_level", "metadata_suggestions", ["confidence_level"])
    op.create_index("ix_metadata_suggestions_status", "metadata_suggestions", ["status"])
    op.create_index("ix_metadata_suggestions_created_at", "metadata_suggestions", ["created_at"])
    op.create_index("uq_metadata_suggestions_current_review", "metadata_suggestions", ["entity_type", "entity_id", "field_name"], unique=True, sqlite_where=sa.text("status IN ('accepted', 'applied')"))

    op.create_table(
        "metadata_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entity_type", sa.String(20), nullable=False), sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("field_name", sa.String(80), nullable=False),
        sa.Column("previous_value", sa.Text()), sa.Column("new_value", sa.Text()),
        sa.Column("provider", sa.String(80)), sa.Column("provider_entity_id", sa.String(255)),
        sa.Column("confidence", sa.Float()), sa.Column("changed_at", sa.DateTime(), nullable=False),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="SET NULL")),
        sa.Column("change_source", sa.String(120), nullable=False),
        sa.Column("audio_file_modified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reversible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("reversal_of_history_id", sa.Integer(), sa.ForeignKey("metadata_history.id", ondelete="SET NULL")),
        sa.CheckConstraint("entity_type IN ('song', 'album', 'artist')", name="ck_metadata_history_entity_type"),
    )
    op.create_index("ix_metadata_history_entity", "metadata_history", ["entity_type", "entity_id", "changed_at"])
    op.create_index("ix_metadata_history_changed_at", "metadata_history", ["changed_at"])


def downgrade() -> None:
    op.drop_table("metadata_history")
    op.drop_table("metadata_suggestions")
