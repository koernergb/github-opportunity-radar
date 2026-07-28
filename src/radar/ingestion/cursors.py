"""Safe incremental cursor reads and writes."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.db.models import SyncCursor


def cursor_since(
    session: Session,
    *,
    scope_type: str,
    scope_key: str,
    overlap_minutes: int,
    full: bool = False,
) -> datetime | None:
    """Return the overlapped cursor without mutating persisted state."""
    if full:
        return None
    cursor = session.scalar(
        select(SyncCursor).where(
            SyncCursor.scope_type == scope_type,
            SyncCursor.scope_key == scope_key,
        )
    )
    if cursor is None or cursor.time_cursor is None:
        return None
    return cursor.time_cursor - timedelta(minutes=overlap_minutes)


def advance_cursor(
    session: Session,
    *,
    scope_type: str,
    scope_key: str,
    time_cursor: datetime,
    succeeded_at: datetime,
    metadata: dict[str, object] | None = None,
) -> None:
    """Advance only after the caller has completed its bounded traversal."""
    cursor = session.scalar(
        select(SyncCursor).where(
            SyncCursor.scope_type == scope_type,
            SyncCursor.scope_key == scope_key,
        )
    )
    if cursor is None:
        cursor = SyncCursor(
            scope_type=scope_type,
            scope_key=scope_key,
            time_cursor=time_cursor,
            token_cursor=None,
            last_success_at=succeeded_at,
            cursor_metadata=metadata or {},
        )
        session.add(cursor)
    else:
        cursor.time_cursor = time_cursor
        cursor.last_success_at = succeeded_at
        cursor.cursor_metadata = metadata or {}
