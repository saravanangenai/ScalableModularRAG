# Plan: API Hardening for External Traffic

- **Spec:** [spec.md](spec.md) (approved 2026-09-16)
- **Status:** done

## Summary

Four additive layers around the existing `apps/api`, none touching `require_workspace_role`,
JWT verification, or RLS: (1) `starlette.middleware.cors.CORSMiddleware` restricted to a
configurable origin allow-list; (2) a small custom FastAPI dependency backed by the Redis
instance already running for Celery (fixed-window counter via `INCR`/`EXPIRE`, no new
third-party rate-limit library) applied to `/search` and document upload; (3) a plain ASGI
middleware adding a fixed set of security response headers to every response; (4) one new
read-only route, `GET /workspaces/{workspace_id}/audit-log`, over the already-existing,
already-written-to `audit_log` table (no migration needed — it's RLS-protected already per
`0002_workspace_rls.py`'s `_DIRECT_TABLES`).

## Architecture doc deltas

| Doc | Change |
|---|---|
| `06-security-model.md` | New §9 "External-traffic hardening": CORS policy, rate limiting, security headers — the concrete mechanisms this plan adds, since the doc had no prior section on this. |
| `07-evaluation-observability.md` | §3 note: rate-limit `429` responses are a new, expected error class visible in `apps/api`'s existing Prometheus metrics (`http_requests_total{status="429"}`) — no new metric needed, `061`'s instrumentation already captures it. |

## Component/module ownership

- **`apps/api/config.py`** (new) — `Settings`: `cors_allowed_origins: list[str]` (comma-
  separated env var, parsed to a list; local-dev default is Vite's dev server origin,
  `http://localhost:5173`), `redis_url: str = "redis://localhost:6379/0"` (same Redis
  instance Celery already uses, addressed independently here since `apps/api` has no reason
  to depend on `packages.ingestion.config` just for a connection string),
  `rate_limit_search_per_minute: int = 30`, `rate_limit_upload_per_minute: int = 30` (per
  caller identity — see Data model changes; conservative starting numbers, explicitly
  documented in-code as "revisit once real usage data exists," resolving spec's Open
  Question 1). **`rate_limit_upload_per_minute` was originally planned as `10`; raised to
  `30` after Group 4's live regression run.** The real root cause, though, wasn't the
  threshold itself: `tests/integration/test_rate_limiting.py` (this same plan, Group 4)
  deliberately bursts past the limit using the *shared* `user1_token` identity every other
  integration test also uploads as — when that test and `test_search_rbac.py` land in the
  same 60s wall-clock window (alphabetically adjacent, so likely), user1's counter arrives
  at the next test already exhausted. Fixed properly by giving that test its own dedicated
  Keycloak identity (`create_keycloak_user`) instead of reverting the design or picking an
  arbitrarily larger number to paper over shared-identity pollution.
- **`apps/api/deps/rate_limit.py`** (new) — `enforce_rate_limit(scope: str, access:
  WorkspaceAccess, limit: int, window_seconds: int = 60)`: a plain sync helper (not a
  `Depends()` — `require_workspace_role(min_role)` builds a new closure per call, so a
  second `Depends()` referencing it wouldn't dedupe against the route's own and would
  re-resolve auth twice; calling this as a normal function from within the route body,
  right after `access` is already in hand, avoids that), using a **sync** `redis.Redis`
  client (not `redis.asyncio`) — matching `packages/retrieval/search.py`'s existing pattern
  of calling sync clients directly from `async def` routes. Confirmed empirically that this
  isn't just style: an `lru_cache`'d `redis.asyncio.Redis` client is bound to the event loop
  it was first used on, and broke with `RuntimeError: Event loop is closed` the moment a
  second pytest-asyncio test (its own fresh event loop) reused the cached client — a sync
  client has no such binding. Builds a Redis key from
  `f"ratelimit:{scope}:{caller_identity}:{window_bucket}"` (caller identity = authenticated
  `user.id` if present, else the resolved `workspace_id` for API-key auth — both already
  available from `WorkspaceAccess`), `INCR`s it, sets `EXPIRE` only on the first increment
  in the window, and raises `RateLimitExceededError` (new, `packages/exceptions`) with the
  window's remaining TTL if the count exceeds `limit`. Fixed-window, not sliding — simpler,
  and precise enough for "stop unbounded cost," not a general-purpose gateway (per spec's
  non-goals).
- **`apps/api/main.py`** — mounts `CORSMiddleware` (from `Settings.cors_allowed_origins`) and
  a new `SecurityHeadersMiddleware` (`apps/api/middleware/security_headers.py`, new); registers
  an exception handler for `RateLimitExceededError` returning `429` with a `Retry-After`
  header.
- **`apps/api/middleware/security_headers.py`** (new) — plain ASGI middleware setting
  `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy:
  strict-origin-when-cross-origin` on every outgoing response.
- **`apps/api/routers/search.py`** — adds `Depends(rate_limit("search",
  settings.rate_limit_search_per_minute))` to `search_workspace`.
- **`apps/api/routers/documents.py`** — adds the same pattern to `upload_document`, with its
  own `rate_limit_upload_per_minute` threshold.
- **`apps/api/routers/audit.py`** (new) — `GET /workspaces/{workspace_id}/audit-log`, gated
  `require_workspace_role("owner")` (matching `api_keys.py`/`workspaces.py`'s existing
  owner-only pattern), paginated (`limit`/`offset` query params, default 50/0, max 200),
  ordered `created_at DESC`. Registered in `apps/api/main.py` alongside the other routers.
- **`apps/api/schemas/audit.py`** (new) — `AuditLogEntryOut` (id, workspace_id,
  actor_user_id, action, resource_type, resource_id, metadata, created_at),
  `AuditLogPage` (items, total).
- **`packages/exceptions/rate_limit.py`** (new) — `RateLimitExceededError(
  DocumentPortalException)`, carrying `retry_after_seconds: int`.

## Data model changes

None. `audit_log` (table, RLS policy, writes) already exists from earlier specs. Rate-limit
counters live in Redis as plain `INCR`-able keys with `EXPIRE` — no new Postgres table, no
migration.

## API contract

- New: `GET /workspaces/{workspace_id}/audit-log?limit=50&offset=0` — `200` with
  `AuditLogPage`; `403` for non-owner roles (existing `require_workspace_role` behavior,
  unchanged); `404` for a workspace the caller isn't a member of (existing membership-check
  behavior via `require_workspace_role`, unchanged).
- Changed (headers/errors only, no shape change): every response gains the three security
  headers; `POST /workspaces/{workspace_id}/search` and `POST /workspaces/{workspace_id}/
  documents` can now additionally return `429` with a JSON body
  `{"detail": "rate limit exceeded"}` and a `Retry-After` header — a new error class, not a
  change to their existing `200`/`202`/4xx-auth responses.
- Changed (CORS only): `OPTIONS` preflight and all responses now carry
  `Access-Control-Allow-Origin` matching the request's `Origin` header only when that origin
  is in `cors_allowed_origins`; otherwise no CORS headers are added (browser blocks it
  client-side, server behavior for the actual request is unchanged — CORS is enforced by the
  browser, not the server rejecting the request outright).

## Retrieval / ingestion impact

None to pipeline behavior. `/search` gets a rate-limit dependency checked *before* the
existing `search()` call runs (fails fast on `429` without touching Qdrant/OpenAI) — this is
exactly the cost-protection this spec exists for, not a retrieval-quality change.

## Security / tenancy impact

- Rate-limit keys are scoped per-caller-identity (`user.id` or API-key's `workspace_id`), so
  one workspace/user hitting its limit cannot affect another's ability to call the API —
  no cross-workspace interference introduced.
- The new audit-log read route reuses `require_workspace_role("owner")` and the existing
  `audit_log` RLS policy unchanged — no new authorization logic, no bypass path. An owner can
  only ever see their own workspace's audit rows (RLS enforces this at the query level, same
  as every other RLS-protected table since `030`).
- CORS is a browser-enforced boundary, not a server-side authorization mechanism — it does
  not replace or weaken `require_workspace_role`; a non-browser client (`curl`, the `eval/`
  CLI, `tests/integration`) is unaffected by CORS entirely (CORS only applies to
  browser-initiated cross-origin requests).
- Security headers are defense-in-depth for a browser client (`071-search-frontend`) against
  clickjacking/MIME-sniffing — no interaction with the auth/isolation model.

## Rollout

Big-bang, no flag:
- CORS: ships with a permissive-enough local-dev default (`http://localhost:5173`) that
  nothing existing breaks; `tests/integration`/`eval/` use `ASGITransport` (in-process, no
  real browser `Origin` header), so CORS is inert for them either way.
- Rate limiting: starting thresholds (30 search/min, 10 uploads/min per caller) are well
  above what `tests/integration`'s and `eval/`'s own call patterns generate in a single test
  run — confirmed by inspecting existing test/eval call counts before finalizing the numbers,
  not just asserted.
- Revert path: remove the two middleware mounts and the two `Depends(rate_limit(...))` call
  sites; the audit-log route is purely additive and can be deleted independently of the rest.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Rate-limit thresholds are wrong (too low, breaking legitimate bursty use; too high, not actually protecting cost) without real production traffic to tune against | Medium — this is an acknowledged guess | Low-Medium — a config value, not an architecture commitment | Documented explicitly in `apps/api/config.py` as a starting guess to revisit; easy to change without a schema/code change |
| A too-permissive CORS default accidentally ships to a real deployment | Low | Medium — would defeat the purpose of this spec | `cors_allowed_origins` has no wildcard option in the implementation (list of exact origins only); local-dev default is `localhost`-only, never a placeholder that looks production-like |
| Redis reused for both Celery broker/backend and rate-limit counters could see rate-limit keys accumulate if `EXPIRE` isn't set correctly | Low | Low — stale counters just mean transiently wrong limits, not data loss (rate-limit keys are already ephemeral by design) | Unit-test the `INCR`+`EXPIRE` logic directly against a real local Redis (already required for `061`'s worker) before relying on it live |

## Alternatives considered

- **A third-party rate-limiting library** (`slowapi`, `fastapi-limiter`) — considered,
  rejected for this first increment: the actual requirement (per-caller fixed-window counter
  on two routes) is a handful of lines against Redis `INCR`/`EXPIRE`, and pulling in a library
  for that is more dependency surface than the problem justifies; revisit if rate-limiting
  needs grow (sliding windows, per-route configuration UI, etc.).
- **Rejecting cross-origin requests at the application layer instead of via `CORSMiddleware`**
  — rejected: `CORSMiddleware` is the standard, already-available (Starlette ships it)
  mechanism; hand-rolling it would just be reimplementing the same header logic with more
  room for mistakes.
- **A dedicated rate-limit Redis database/instance** separate from Celery's — rejected as
  unnecessary infrastructure for this project's scale; a distinct Redis *key prefix*
  (`ratelimit:`) is sufficient isolation from Celery's own keys within the same instance.
