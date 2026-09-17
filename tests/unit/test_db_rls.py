import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text

from packages.db.rls import set_workspace_scope, set_workspace_scope_sync
from packages.exceptions import DatabaseError


async def test_set_workspace_scope_issues_transaction_local_set_config():
    session = AsyncMock()
    workspace_id = uuid.uuid4()

    await set_workspace_scope(session, workspace_id)

    session.execute.assert_awaited_once()
    statement, params = session.execute.await_args.args
    assert statement.compare(text("SELECT set_config(:name, :value, true)"))
    assert params == {"name": "app.current_workspace_id", "value": str(workspace_id)}


async def test_set_workspace_scope_wraps_failures():
    session = AsyncMock()
    session.execute.side_effect = RuntimeError("boom")

    with pytest.raises(DatabaseError):
        await set_workspace_scope(session, uuid.uuid4())


def test_set_workspace_scope_sync_issues_session_local_set_config():
    session = MagicMock()
    workspace_id = uuid.uuid4()

    set_workspace_scope_sync(session, workspace_id)

    session.execute.assert_called_once()
    statement, params = session.execute.call_args.args
    assert statement.compare(text("SELECT set_config(:name, :value, false)"))
    assert params == {"name": "app.current_workspace_id", "value": str(workspace_id)}


def test_set_workspace_scope_sync_wraps_failures():
    session = MagicMock()
    session.execute.side_effect = RuntimeError("boom")

    with pytest.raises(DatabaseError):
        set_workspace_scope_sync(session, uuid.uuid4())
