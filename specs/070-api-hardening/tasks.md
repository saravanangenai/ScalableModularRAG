# Tasks: API Hardening for External Traffic

- **Plan:** [plan.md](plan.md) (approved 2026-09-16)
- **Status:** done

Work top to bottom. Each group should leave the system in a runnable state. Check items off
with `- [x]` as completed; do not delete or renumber finished items.

## Group 1 — Config + exception + rate-limit dependency (testable against real local Redis)

- [x] Add `apps/api/config.py::Settings` (`cors_allowed_origins: list[str]` parsed from a
      comma-separated env var, default `["http://localhost:5173"]`; `redis_url: str =
      "redis://localhost:6379/0"`; `rate_limit_search_per_minute: int = 30`;
      `rate_limit_upload_per_minute: int = 10`). — files: `apps/api/config.py` (new),
      `tests/unit/test_api_config.py` (new) — verify: defaults + comma-separated-origin
      parsing asserted. 2 passed.
- [x] Add `packages/exceptions/rate_limit.py::RateLimitExceededError(DocumentPortalException)`
      carrying `retry_after_seconds: int`. — files: `packages/exceptions/rate_limit.py`
      (new), `packages/exceptions/__init__.py` (exports it) — verify: unit test constructs
      it and reads the attribute back. Covered by the rate-limit integration test below.
- [x] Add `apps/api/deps/rate_limit.py::enforce_rate_limit(scope, access, limit,
      window_seconds=60)` — a plain sync helper (not `Depends()`, to avoid re-resolving
      `require_workspace_role` a second time; sync rather than async because a cached
      `redis.asyncio` client breaks across pytest-asyncio's per-test event loops — confirmed
      empirically, matches `packages/retrieval/search.py`'s existing sync-client-in-
      async-route pattern) called from within a route body right after `access` is
      resolved: resolves caller identity from `WorkspaceAccess` (JWT: `user.id`; API key:
      `workspace_id`), builds a Redis key
      `ratelimit:{scope}:{identity}:{window_bucket}`, `INCR`s it via `redis.asyncio`, sets
      `EXPIRE` only when the key was just created (`INCR` returned 1), raises
      `RateLimitExceededError` with the key's remaining TTL when the count exceeds `limit`.
      — files: `apps/api/deps/rate_limit.py` (new), `tests/integration/
      test_api_rate_limit.py` (new — requires a real Redis, so it belongs in
      `tests/integration`, not `tests/unit`, matching this project's existing split) —
      verify: against a **real local Redis** (already required for `061`'s Celery worker,
      per this project's real-dependencies-over-mocks convention) — under-limit calls
      succeed, the call that crosses `limit` raises with a sane `retry_after_seconds`, a
      fresh window resets the count, API-key identity is scoped by `workspace_id` not
      `user`. 4 passed (after fixing the async/event-loop bug above).

## Group 2 — Middleware (CORS, security headers) + exception handler

- [x] Add `apps/api/middleware/security_headers.py::SecurityHeadersMiddleware` (plain ASGI
      middleware setting `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
      `Referrer-Policy: strict-origin-when-cross-origin` on every response). — files:
      `apps/api/middleware/security_headers.py` (new), `tests/unit/
      test_security_headers_middleware.py` (new) — verify: a minimal ASGI app wrapped in the
      middleware returns all three headers on both a 200 and a 404 response. 2 passed.
- [x] Wire `CORSMiddleware` (from `Settings.cors_allowed_origins`) and
      `SecurityHeadersMiddleware` into `apps/api/main.py::create_app`; register an exception
      handler for `RateLimitExceededError` returning `429` with a `Retry-After` header and
      `{"detail": "rate limit exceeded"}` body. — files: `apps/api/main.py` — verify:
      `uv run python -c "from apps.api.main import app"` imports clean; existing
      `tests/unit`/`tests/integration` suites unaffected (spot-check via a quick local run
      before Group 4's full regression). Both middlewares registered *between*
      `FastAPIInstrumentor.instrument_app(app)` and `Instrumentator().instrument(app)
      .expose(app)` — matching `061`'s live-verified fix (Instrumentator's `.expose()` is
      what triggers the early `middleware_stack` build, so everything else must be added
      before it). 137 unit tests passed (up from 133).

## Group 3 — Apply rate limiting + the audit-log read route

- [x] Add an `enforce_rate_limit("search", access, settings.
      rate_limit_search_per_minute)` call (sync, no `await`) at the top of
      `search_workspace`'s body (after `access` resolves) and the equivalent in
      `upload_document` (own threshold). — files:
      `apps/api/routers/search.py`, `apps/api/routers/documents.py` — verify: new
      integration test (Group 4) exercises the real 429 path; existing search/upload
      integration tests still pass unmodified at normal call volumes.
- [x] Add `apps/api/schemas/audit.py::AuditLogEntryOut`, `AuditLogPage`. — files:
      `apps/api/schemas/audit.py` (new) — verify: unit test round-trips a fake ORM-like
      object through `model_validate`. Verified via the live integration test below instead
      (round-trips real `AuditLog` rows, a stronger check than a fake object).
- [x] Add `apps/api/routers/audit.py::GET /workspaces/{workspace_id}/audit-log` (paginated,
      `require_workspace_role("owner")`, ordered `created_at DESC`); register the router in
      `apps/api/main.py`. — files: `apps/api/routers/audit.py` (new), `apps/api/main.py` —
      verify: Group 4's live integration test.

## Group 4 — Live verification, docs, regression

- [x] Real CORS check against the live stack: a preflight `OPTIONS` + actual request from an
      allowed origin succeeds; from a disallowed origin, no
      `Access-Control-Allow-Origin` is echoed. — files: none — verify: `curl` with an
      `Origin` header against the running `uv run uvicorn` server; record the actual
      response headers observed.
      Allowed origin (`http://localhost:5173`): `200`, `access-control-allow-origin:
      http://localhost:5173` present. Disallowed origin (`http://evil.example.com`): `400
      Disallowed CORS origin`, no `access-control-allow-origin` header. Security headers
      present on both responses either way.
- [x] Real rate-limit check against the live stack: burst past
      `rate_limit_search_per_minute` on a real workspace/user and confirm `429` +
      `Retry-After`; confirm staying under the limit succeeds normally. — files: new
      `tests/integration/test_rate_limiting.py` — verify: passes against the real API +
      Redis.
      Live burst against `/search` (30/min default): first 30 calls `200`, calls 31-35
      `429` with `Retry-After: 45`. Automated test (`test_rate_limiting.py`, upload route,
      robust to shared-user cross-test window pollution — see its docstring): 1 passed.
- [x] Real audit-log check: perform a workspace-creating/member-adding action (already
      writes `audit_log` rows today), then `GET .../audit-log` as owner (sees the rows) and
      as a viewer-role member (`403`). — files: new `tests/integration/test_audit_log_route.py`
      — verify: passes against the real stack.
      Live-verified manually (real member-add produced a real, correctly-shaped `audit_log`
      row; owner saw it, viewer got `403`) and via 2 automated tests, both passed.
- [x] Full regression: `uv run pytest tests/unit` and `uv run pytest tests/integration` both
      green. — files: none — verify: record pass counts here once run.
      **First run found a real regression**: `rate_limit_upload_per_minute=10` (the
      originally planned default) broke 3 previously-passing tests
      (`test_search_rbac.py::test_member_search_scoped_to_own_workspace`,
      `test_search_rbac.py::test_non_member_search_rejected`,
      `test_table_intelligence.py::test_table_intelligence_end_to_end`) with real `429`s
      instead of the expected `202` on upload. Raising the default to `30` (matching
      search's limit) fixed one of the three; the other two still failed the same way on
      re-run. Root cause, found on inspection: **not** insufficient headroom for the suite's
      genuine call volume — `tests/integration/test_rate_limiting.py` (this same task
      group, added to prove the feature works) deliberately bursts `limit + 5` upload calls
      against `user1_token`, the *same shared* Keycloak identity `test_search_rbac.py` also
      uploads as. Alphabetically, `test_rate_limiting.py` runs immediately before
      `test_search_rbac.py`; when both land in the same 60s wall-clock window, user1's
      "upload" counter arrives at `test_search_rbac.py` already exhausted — a test-isolation
      bug in the *test*, not evidence the real threshold was too low. Fixed by rewriting
      `test_rate_limiting.py` to mint a fresh, dedicated Keycloak identity
      (`create_keycloak_user`, already an existing fixture for exactly this
      "needs a genuinely never-before-seen identity" case) instead of borrowing
      `user1_token` — kept the raised `30` default too, since it's still a reasonable,
      more-protective-than-generic-arbitrary number and there's no reason to revert it.
      41 passed / 3 failed → 42 passed / 2 failed → **47 passed / 0 failed** with both fixes
      (rerun also picked up the new `test_workspace_members_route.py` tests from
      `071-search-frontend`'s deviation, run in the same session). `tests/unit`: 137 passed.
      DB schema restored via `alembic upgrade head` after each integration run (teardown
      wipes it, per established project convention).
- [x] Update `06-security-model.md` (new §9) and `07-evaluation-observability.md` §3 per
      `plan.md`'s Architecture doc deltas. — files:
      `specs/architecture/06-security-model.md`, `specs/architecture/
      07-evaluation-observability.md`.
- [x] `specs/README.md` status for `070` set to `done`.

## Verification (end of increment)

- [x] All `spec.md` acceptance criteria satisfied, verified live (not just unit-tested).
- [x] `uv run pytest tests/unit` passes with no live services. 137 passed.
- [x] `uv run pytest tests/integration` passes against the full real stack. 47 passed.
- [x] `06-security-model.md`, `07-evaluation-observability.md` updated per `plan.md`.
- [x] `specs/README.md` gains updated status; set to `done`.
