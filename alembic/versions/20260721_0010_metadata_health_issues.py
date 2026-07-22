"""Add durable provider-neutral metadata health issues."""

from alembic import op
import sqlalchemy as sa

revision = "20260721_0010"
down_revision = "20260721_0009"
branch_labels = None
depends_on = None

def upgrade() -> None:
    # SQLite persists DDL even if the process exits before Alembic records the
    # revision. Make a restart resume an interrupted upgrade instead of
    # failing forever with "table metadata_issues already exists".
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "metadata_issues" not in inspector.get_table_names():
        op.create_table(
            "metadata_issues",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("identity_key", sa.String(128), nullable=False),
            sa.Column("rule_id", sa.String(100), nullable=False),
            sa.Column("rule_version", sa.String(20), nullable=False, server_default="1"),
            sa.Column("entity_type", sa.String(20), nullable=False),
            sa.Column("entity_id", sa.String(255), nullable=False),
            sa.Column("song_id", sa.Integer),
            sa.Column("album_key", sa.String(500)),
            sa.Column("artist_key", sa.String(500)),
            sa.Column("field_name", sa.String(80)),
            sa.Column("severity", sa.String(20), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="open"),
            sa.Column("title", sa.String(300), nullable=False),
            sa.Column("explanation", sa.String(1000), nullable=False),
            sa.Column("current_value", sa.Text),
            sa.Column("normalized_value", sa.Text),
            sa.Column("suggested_action", sa.String(500)),
            sa.Column(
                "automatically_repairable",
                sa.Boolean,
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column("evidence", sa.Text),
            sa.Column("first_detected_at", sa.DateTime, nullable=False),
            sa.Column("last_detected_at", sa.DateTime, nullable=False),
            sa.Column("resolved_at", sa.DateTime),
            sa.Column("ignored_at", sa.DateTime),
            sa.Column(
                "detection_job_id",
                sa.Integer,
                sa.ForeignKey("tasks.id", ondelete="SET NULL"),
            ),
            sa.CheckConstraint(
                "entity_type IN ('song', 'album', 'artist')",
                name="ck_metadata_issue_entity_type",
            ),
            sa.CheckConstraint(
                "severity IN ('info', 'warning', 'error', 'critical')",
                name="ck_metadata_issue_severity",
            ),
            sa.CheckConstraint(
                "status IN ('open', 'resolved', 'ignored')",
                name="ck_metadata_issue_status",
            ),
        )

    existing_indexes = {
        index["name"] for index in sa.inspect(bind).get_indexes("metadata_issues")
    }
    for name, columns, kwargs in (
        ("uq_metadata_issue_identity", ["identity_key"], {"unique": True}),
        (
            "ix_metadata_issues_filter",
            ["status", "severity", "rule_id", "entity_type"],
            {},
        ),
        ("ix_metadata_issues_detected", ["last_detected_at"], {}),
    ):
        if name not in existing_indexes:
            op.create_index(name, "metadata_issues", columns, **kwargs)


def downgrade() -> None:
    op.drop_table("metadata_issues")
