import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from packages.exceptions import DatabaseError

#: Session GUC the Row-Level Security policies in migration 0002 key off. Set once per
#: request (packages/db/migrations/versions/0002_workspace_rls.py; wired in from
#: apps/api/deps/rbac.py::require_workspace_role), transaction-local via set_config's third
#: argument — it resets automatically at commit/rollback, matching the one-session-per-request
#: lifecycle in apps/api/deps/db.py::get_db_session.
_WORKSPACE_GUC = "app.current_workspace_id"


async def set_workspace_scope(session: AsyncSession, workspace_id: uuid.UUID) -> None:
    """Sets the transaction-local GUC the workspace RLS policies check. Must be called after
    the caller's role has already been resolved and authorized (require_workspace_role) —
    this only affects what subsequent queries in the same transaction can see, it is not
    itself an authorization check."""
    try:
        await session.execute(
            text("SELECT set_config(:name, :value, true)"),
            {"name": _WORKSPACE_GUC, "value": str(workspace_id)},
        )
    except Exception as exc:
        raise DatabaseError("failed to set workspace RLS scope", original_exception=exc) from exc


def set_workspace_scope_sync(session: Session, workspace_id: uuid.UUID) -> None:
    """Sync counterpart of set_workspace_scope, for the Celery worker's sync Session
    (packages/ingestion/pipeline.py::run_ingestion) — that code path never goes through
    apps/api/deps/rbac.py, so it must set the GUC itself, using the workspace_id the
    already-authorized enqueuing request passed through (workers/celery_app.py), before
    touching any RLS-protected table (ingestion_jobs, document_versions, documents).

    Unlike set_workspace_scope's transaction-local set_config, this one is session-local
    (is_local=false): run_ingestion commits multiple times as a job advances through stages,
    and a transaction-local value would be discarded at the first of those commits, well
    before the job finishes. This is safe because run_ingestion always calls this as its very
    first action for every job — any stale value left over from the connection pool reusing
    this physical connection for an earlier job is overwritten immediately, before any query
    runs."""
    try:
        session.execute(
            text("SELECT set_config(:name, :value, false)"),
            {"name": _WORKSPACE_GUC, "value": str(workspace_id)},
        )
    except Exception as exc:
        raise DatabaseError("failed to set workspace RLS scope", original_exception=exc) from exc
