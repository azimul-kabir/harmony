"""Add provider-neutral metadata suggestions and history."""

from alembic import op
import sqlalchemy as sa

revision = "20260721_0009"
down_revision = "20260721_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite DDL is non-transactional.  If the process is stopped after the
    # tables are created but before Alembic records this revision, the next
    # startup must be able to resume rather than repeatedly failing with
    # "table already exists".  This also repairs databases affected by the
    # previous bootstrap implementation, which could pre-create these tables.
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "metadata_suggestions" not in inspector.get_table_names():
        op.create_table(
            "metadata_suggestions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("entity_type", sa.String(20), nullable=False),
            sa.Column("entity_id", sa.Integer(), nullable=False),
            sa.Column("field_name", sa.String(80), nullable=False),
            sa.Column("current_value", sa.Text()),
            sa.Column("suggested_value", sa.Text()),
            sa.Column("provider", sa.String(80), nullable=False),
            sa.Column("provider_entity_id", sa.String(255)),
            sa.Column("confidence", sa.Float()),
            sa.Column("confidence_level", sa.String(20), nullable=False),
            sa.Column("match_explanation", sa.String(1000)),
            sa.Column("positive_evidence", sa.Text()),
            sa.Column("conflicting_evidence", sa.Text()),
            sa.Column(
                "status", sa.String(20), nullable=False, server_default="pending"
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("reviewed_at", sa.DateTime()),
            sa.Column("applied_at", sa.DateTime()),
            sa.Column("rejected_at", sa.DateTime()),
            sa.Column(
                "created_by_job_id",
                sa.Integer(),
                sa.ForeignKey("tasks.id", ondelete="SET NULL"),
            ),
            sa.Column("reviewed_by", sa.String(120)),
            sa.CheckConstraint(
                "entity_type IN ('song', 'album', 'artist')",
                name="ck_metadata_suggestion_entity_type",
            ),
            sa.CheckConstraint(
                "status IN ('pending', 'accepted', 'rejected', 'superseded', 'applied', 'apply_failed')",
                name="ck_metadata_suggestion_status",
            ),
            sa.CheckConstraint(
                "confidence_level IN ('exact', 'high', 'medium', 'low', 'rejected')",
                name="ck_metadata_suggestion_confidence_level",
            ),
            sa.CheckConstraint(
                "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
                name="ck_metadata_suggestion_confidence",
            ),
        )
    suggestion_indexes = {
        index["name"] for index in sa.inspect(bind).get_indexes("metadata_suggestions")
    }
    for name, columns, kwargs in (
        (
            "ix_metadata_suggestions_entity",
            ["entity_type", "entity_id", "field_name"],
            {},
        ),
        ("ix_metadata_suggestions_pending", ["status", "created_at"], {}),
        ("ix_metadata_suggestions_provider", ["provider"], {}),
        ("ix_metadata_suggestions_confidence_level", ["confidence_level"], {}),
        ("ix_metadata_suggestions_status", ["status"], {}),
        ("ix_metadata_suggestions_created_at", ["created_at"], {}),
        (
            "uq_metadata_suggestions_current_review",
            ["entity_type", "entity_id", "field_name"],
            {
                "unique": True,
                "sqlite_where": sa.text("status IN ('accepted', 'applied')"),
            },
        ),
    ):
        if name not in suggestion_indexes:
            op.create_index(name, "metadata_suggestions", columns, **kwargs)

    if "metadata_history" not in inspector.get_table_names():
        op.create_table(
            "metadata_history",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("entity_type", sa.String(20), nullable=False),
            sa.Column("entity_id", sa.Integer(), nullable=False),
            sa.Column("field_name", sa.String(80), nullable=False),
            sa.Column("previous_value", sa.Text()),
            sa.Column("new_value", sa.Text()),
            sa.Column("provider", sa.String(80)),
            sa.Column("provider_entity_id", sa.String(255)),
            sa.Column("confidence", sa.Float()),
            sa.Column("changed_at", sa.DateTime(), nullable=False),
            sa.Column(
                "job_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="SET NULL")
            ),
            sa.Column("change_source", sa.String(120), nullable=False),
            sa.Column(
                "audio_file_modified",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column(
                "reversible", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
            sa.Column(
                "reversal_of_history_id",
                sa.Integer(),
                sa.ForeignKey("metadata_history.id", ondelete="SET NULL"),
            ),
            sa.CheckConstraint(
                "entity_type IN ('song', 'album', 'artist')",
                name="ck_metadata_history_entity_type",
            ),
        )
    history_indexes = {
        index["name"] for index in sa.inspect(bind).get_indexes("metadata_history")
    }
    for name, columns in (
        ("ix_metadata_history_entity", ["entity_type", "entity_id", "changed_at"]),
        ("ix_metadata_history_changed_at", ["changed_at"]),
    ):
        if name not in history_indexes:
            op.create_index(name, "metadata_history", columns)


def downgrade() -> None:
    op.drop_table("metadata_history")
    op.drop_table("metadata_suggestions")
