from collections.abc import AsyncGenerator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """One session per request, committed on success / rolled back on any exception. Does
    NOT set the app.current_tenant_id GUC itself — that happens once a role-check dependency
    (apps/api/deps/rbac.py) has confirmed the caller's scope, since the GUC target isn't
    known until then."""
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
