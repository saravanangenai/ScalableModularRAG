import time
import uuid

import pytest

from apps.api.deps.rate_limit import enforce_rate_limit
from apps.api.deps.rbac import WorkspaceAccess
from packages.db.models import User
from packages.exceptions import RateLimitExceededError


def _access() -> WorkspaceAccess:
    user = User(
        id=uuid.uuid4(),
        email="ratelimit-test@example.com",
        display_name="Rate Limit Test",
        auth_provider_subject="ratelimit-test",
    )
    return WorkspaceAccess(workspace_id=uuid.uuid4(), user=user, role="viewer")


def test_calls_under_the_limit_succeed():
    access = _access()
    scope = f"test-under-{uuid.uuid4()}"

    for _ in range(3):
        enforce_rate_limit(scope, access, limit=3)


def test_crossing_the_limit_raises_with_a_sane_retry_after():
    access = _access()
    scope = f"test-cross-{uuid.uuid4()}"

    for _ in range(2):
        enforce_rate_limit(scope, access, limit=2, window_seconds=5)

    with pytest.raises(RateLimitExceededError) as exc_info:
        enforce_rate_limit(scope, access, limit=2, window_seconds=5)

    assert 1 <= exc_info.value.retry_after_seconds <= 5


def test_api_key_identity_is_scoped_by_workspace_id_not_user():
    workspace_id = uuid.uuid4()
    access = WorkspaceAccess(workspace_id=workspace_id, user=None, role="owner")
    scope = f"test-apikey-{uuid.uuid4()}"

    for _ in range(2):
        enforce_rate_limit(scope, access, limit=2)

    with pytest.raises(RateLimitExceededError):
        enforce_rate_limit(scope, access, limit=2)


def test_a_fresh_window_resets_the_count():
    access = _access()
    scope = f"test-window-{uuid.uuid4()}"

    enforce_rate_limit(scope, access, limit=1, window_seconds=2)
    with pytest.raises(RateLimitExceededError):
        enforce_rate_limit(scope, access, limit=1, window_seconds=2)

    time.sleep(2.2)
    enforce_rate_limit(scope, access, limit=1, window_seconds=2)
