"""Add immutable configuration revisions and activation history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from radar.db.models import UTCDateTime

revision: str = "0002_config_revisions"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "config_revisions" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "config_revisions",
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("yaml_text", sa.Text(), nullable=False),
        sa.Column("valid", sa.Boolean(), nullable=False),
        sa.Column("validation_errors", sa.JSON(), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=True),
        sa.Column("profile_hash", sa.String(64), nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["supersedes_id"], ["config_revisions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_config_revisions_config_hash", "config_revisions", ["config_hash"])
    op.create_index("ix_config_revisions_profile_hash", "config_revisions", ["profile_hash"])
    op.create_table(
        "config_activations",
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("previous_revision_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["revision_id"], ["config_revisions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["previous_revision_id"], ["config_revisions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_config_activations_revision_id", "config_activations", ["revision_id"])
    op.create_index("ix_config_activations_created", "config_activations", ["created_at", "id"])


def downgrade() -> None:
    tables = sa.inspect(op.get_bind()).get_table_names()
    if "config_activations" in tables:
        op.drop_table("config_activations")
    if "config_revisions" in tables:
        op.drop_table("config_revisions")
