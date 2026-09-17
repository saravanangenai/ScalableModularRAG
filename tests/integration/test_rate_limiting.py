"""Requires real Postgres + Keycloak + Redis (specs/070-api-hardening).

Uses an invalid content-type on every upload call so requests fail fast with 415 rather
than touching storage/Celery/OpenAI — enforce_rate_limit runs before that validation, so
this still exercises the real rate-limit path end-to-end without any ingestion cost.

Uses a fresh, dedicated Keycloak identity (create_keycloak_user) rather than the shared
testuser/testuser2 identities every other integration test uses: this test deliberately
exhausts the real "upload" rate-limit counter, and doing that against a shared identity
poisoned test_search_rbac.py's uploads when both happened to fall in the same 60s wall-clock
window in an earlier run of this suite (confirmed empirically — see
specs/070-api-hardening/tasks.md).
"""

from apps.api.config import Settings as ApiSettings

from tests.integration.test_upload_and_ingest import _auth, _create_workspace


async def test_exceeding_the_upload_rate_limit_returns_429_with_retry_after(
    api_client, mint_token, create_keycloak_user
):
    username, password = create_keycloak_user()
    token = mint_token(username, password)

    workspace_id = await _create_workspace(api_client, token)
    limit = ApiSettings().rate_limit_upload_per_minute

    responses = []
    for _ in range(limit + 5):
        response = await api_client.post(
            f"/workspaces/{workspace_id}/documents",
            files={"file": ("x.txt", b"not a pdf", "text/plain")},
            headers=_auth(token),
        )
        responses.append(response)

    statuses = [r.status_code for r in responses]
    assert set(statuses) <= {415, 429}, f"unexpected status codes: {statuses}"
    assert 429 in statuses, "bursting past the limit never triggered a 429"

    rate_limited = next(r for r in responses if r.status_code == 429)
    assert "Retry-After" in rate_limited.headers
    assert int(rate_limited.headers["Retry-After"]) > 0
    assert rate_limited.json() == {"detail": "rate limit exceeded"}

    # Once limited, every subsequent call in the same window stays limited.
    first_429_index = statuses.index(429)
    assert all(s == 429 for s in statuses[first_429_index:])
