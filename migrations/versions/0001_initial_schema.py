"""Create the complete initial observation and derivation schema."""

from collections.abc import Sequence

from alembic import op

from radar.db.models import Base

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create all version-one tables and indexes."""
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    """Drop all version-one tables and indexes."""
    Base.metadata.drop_all(bind=op.get_bind())
