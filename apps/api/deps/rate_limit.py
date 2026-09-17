import time
from functools import lru_cache

from redis import Redis

from apps.api.config import Settings
from apps.api.deps.rbac import WorkspaceAccess
from packages.exceptions import RateLimitExceededError


@lru_cache(maxsize=1)
def _redis_client() -> Redis:
    return Redis.from_url(Settings().redis_url, decode_responses=True)


def enforce_rate_limit(
    scope: str, access: WorkspaceAccess, limit: int, window_seconds: int = 60
) -> None:
    """Fixed-window rate limit keyed by caller identity (JWT user id, or the API key's
    workspace_id when access.user is None). Call after require_workspace_role has already
    resolved access, before any expensive/paid work in the route body. Uses a plain sync
    Redis client (not redis.asyncio) — matching packages/retrieval/search.py's existing
    pattern of calling sync clients directly from async routes — since redis.asyncio's
    client is bound to the event loop it was created on, which breaks under pytest-asyncio's
    per-test event loops when the client is cached across tests (confirmed empirically:
    "RuntimeError: Event loop is closed" on the second test to reuse the cached client);
    a plain sync client has no such binding.
    """
    identity = str(access.user.id) if access.user is not None else f"apikey:{access.workspace_id}"
    window_bucket = int(time.time()) // window_seconds
    key = f"ratelimit:{scope}:{identity}:{window_bucket}"

    client = _redis_client()
    count = client.incr(key)
    if count == 1:
        client.expire(key, window_seconds)

    if count > limit:
        ttl = client.ttl(key)
        raise RateLimitExceededError("rate limit exceeded", retry_after_seconds=max(ttl, 1))
