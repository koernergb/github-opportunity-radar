"""Add persisted assistant conversations, messages, and read-tool provenance."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from radar.db.models import UTCDateTime

revision: str = "0003_assistant_conversations"
down_revision: str | None = "0002_config_revisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "conversations" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "conversations",
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "conversation_messages",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=True),
        sa.Column("provider", sa.String(64), nullable=True),
        sa.Column("model_version", sa.String(255), nullable=True),
        sa.Column("usage_json", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversation_messages_conversation_id", "conversation_messages", ["conversation_id"]
    )
    op.create_index(
        "ix_conversation_messages_order", "conversation_messages", ["conversation_id", "created_at"]
    )
    op.create_table(
        "assistant_tool_calls",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.String(255), nullable=False),
        sa.Column("tool_name", sa.String(64), nullable=False),
        sa.Column("arguments_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["conversation_messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_assistant_tool_calls_conversation_id", "assistant_tool_calls", ["conversation_id"]
    )
    op.create_index("ix_assistant_tool_calls_message_id", "assistant_tool_calls", ["message_id"])


def downgrade() -> None:
    tables = sa.inspect(op.get_bind()).get_table_names()
    for table in ("assistant_tool_calls", "conversation_messages", "conversations"):
        if table in tables:
            op.drop_table(table)
