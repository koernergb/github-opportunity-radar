"""Add single-use conversational configuration proposals."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from radar.db.models import UTCDateTime

revision: str = "0004_assistant_proposals"
down_revision: str | None = "0003_assistant_conversations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "assistant_change_proposals" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "assistant_change_proposals",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("base_revision_id", sa.Uuid(), nullable=False),
        sa.Column("resulting_revision_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("arguments_json", sa.JSON(), nullable=False),
        sa.Column("proposed_config", sa.JSON(), nullable=False),
        sa.Column("argument_hash", sa.String(64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.Column("resolved_at", UTCDateTime(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["base_revision_id"], ["config_revisions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["resulting_revision_id"], ["config_revisions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_assistant_change_proposals_conversation_id",
        "assistant_change_proposals",
        ["conversation_id"],
    )
    op.create_index(
        "ix_assistant_proposals_status_expiry",
        "assistant_change_proposals",
        ["status", "expires_at"],
    )


def downgrade() -> None:
    if "assistant_change_proposals" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("assistant_change_proposals")
