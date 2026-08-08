"""Add durable local scheduling state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from radar.db.models import UTCDateTime

revision: str = "0005_local_schedule"
down_revision: str | None = "0004_assistant_proposals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "local_schedules" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "local_schedules",
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(128), nullable=False),
        sa.Column("next_run_at", UTCDateTime(), nullable=True),
        sa.Column("last_attempt_at", UTCDateTime(), nullable=True),
        sa.Column("last_status", sa.String(64), nullable=True),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    if "local_schedules" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("local_schedules")
