# Spec: API Hardening for External Traffic

- **ID:** `070-api-hardening`
- **Roadmap phase:** [08-roadmap.md](../architecture/08-roadmap.md) Phase 8 — Production API
  + Frontend (`070-079`), the "harden `apps/api` for external traffic" half —
  [`06-security-model.md`](../architecture/06-security-model.md). Sibling to
  `071-search-frontend` (the new public UI) — split out because hardening is a backend-only
  concern independently testable via `curl`/pytest, while the frontend is a new app surface
  with its own (auth-flow) design questions; they don't share code.
- **Status:** done
- **Owner:** Saravanan Shanmugam
- **Date:** 2026-09-16

## Problem statement

Every route in `apps/api` today assumes a trusted caller: integration tests, the `eval/` CLI,
or a developer's own terminal. There is no CORS policy (a browser-based frontend calling
this API from a different origin — `071-search-frontend` — would be silently blocked or,
worse, wide open if a permissive wildcard were added carelessly), no rate limiting (a single
caller can issue unlimited `/search` requests, each triggering a real paid OpenAI embedding
call plus a Qdrant query — `030`/`040`), and no systematic input-size limits beyond what
`documents.py`'s upload route already checks ad hoc (413/415 for file size/type). Exposing
this API to real browser traffic without these baseline protections would mean shipping a
nicer frontend on top of an abusable backend — exactly what `08-roadmap.md` names as the
reason Phase 8 comes after isolation/observability, not before.

Separately, `audit_log` (`02-data-model.md`) already exists and is already written to
(`workspaces.py`, `api_keys.py` call `packages.db.audit.write_audit_log` today) but nothing
reads it back — there is no way for a workspace owner to see their own audit trail short of
querying Postgres directly.

## Goals

- A CORS policy on `apps/api` restricting cross-origin requests to the deployed frontend's
  origin(s) (configurable, not a wildcard `*`) — the specific, minimum-necessary opening for
  `071-search-frontend` to call this API from a browser.
- Per-caller rate limiting on cost-bearing routes at minimum (`/search`, document upload) —
  enough to stop a single caller from generating unbounded OpenAI/Qdrant spend or starving
  other workspaces, not a general-purpose API gateway.
- Consistent security response headers (e.g. `X-Content-Type-Options`,
  `X-Frame-Options`/`frame-ancestors`, `Referrer-Policy`) applied uniformly across routes via
  middleware, not per-route.
- A read endpoint over the existing `audit_log` table, scoped to the caller's workspace and
  gated to `owner` role (matching `api_keys`/`workspaces`'s existing owner-only pattern) — the
  first genuinely useful "admin" capability Phase 8 can ship, since the table and its writes
  already exist.
- An explicit, documented review of existing input validation (upload size/type limits,
  search `k`/query-length bounds) confirming it's systematic rather than ad hoc, closing any
  gaps found.

## Non-goals

- **Not** `usage_quotas` enforcement or billing — that table doesn't exist in the
  single-tenant as-built schema (`012` dropped it with the tenant layer); quota enforcement
  is Phase 9/10 scope, once multi-tenancy and billing return.
- **Not** a full API gateway, WAF, or DDoS protection — this is application-level hardening
  (CORS/rate-limit/headers/validation) within `apps/api` itself, not infrastructure in front
  of it.
- **Not** admin write endpoints (revoking another user's access, editing quotas) — only a
  read endpoint over `audit_log`, matching what already exists to read.
- **Not** the frontend itself — that's `071-search-frontend`.
- **Not** a change to the authentication mechanism (Keycloak JWT verification,
  `require_workspace_role`) — this spec adds policy layers around existing auth, it doesn't
  change how identity or authorization is established.

## User-facing behavior

No new end-user UI; this is the API surface `071-search-frontend`'s browser client depends
on, plus one new admin-facing endpoint.

- A browser page served from the deployed frontend's origin can call `apps/api` and receive
  successful CORS preflight/response headers; a request from any other origin is rejected by
  the browser (server sends no matching `Access-Control-Allow-Origin`).
- A caller that exceeds the configured rate limit on `/search` or document upload receives a
  `429 Too Many Requests` with a `Retry-After` hint, instead of the request succeeding and
  silently running up cost.
- A workspace owner can call `GET /workspaces/{workspace_id}/audit-log` and see a
  paginated list of that workspace's audit events (actor, action, timestamp) — the same rows
  `write_audit_log` already produces, now readable.
- Every `apps/api` response carries the new security headers regardless of route or status
  code.

## Acceptance criteria

- [x] A cross-origin browser request from an origin *not* in the configured allow-list is
      rejected (no `Access-Control-Allow-Origin` echoed back); a request from an allowed
      origin succeeds, verified with a real preflight (`OPTIONS`) + actual request.
      Verified live: allowed origin got `200` + matching header; disallowed origin got `400
      Disallowed CORS origin`, no header.
- [x] Exceeding the configured rate limit on `/search` (or upload) within the configured
      window returns `429` with a `Retry-After` header; staying under it succeeds normally —
      verified with a real burst of requests against the live stack, not mocked.
      Verified live against `/search` (30 calls `200`, then `429`+`Retry-After: 45`) and via
      an automated integration test against the real upload route.
- [x] Every response from `apps/api` (success and error) carries the new security headers,
      verified against at least one route of each kind (JSON success, 4xx error, `/metrics`).
      Verified via `SecurityHeadersMiddleware` unit tests (200 and 404) and live CORS checks
      (headers present on both the allowed and disallowed-origin responses).
- [x] `GET /workspaces/{workspace_id}/audit-log` returns real, paginated `audit_log` rows for
      an `owner`-role caller and `403`s for a `viewer`/`editor`-role caller, matching the
      existing RBAC pattern (`api_keys.py`, `workspaces.py`).
      Verified live (real member-add produced a real row; owner saw it, viewer got `403`)
      and via 2 automated integration tests.
- [x] `uv run pytest tests/unit` passes with no live services. 137 passed.
- [x] The full existing integration suite (`020` through `061`) still passes unmodified —
      hardening must not change any existing route's success-path behavior or error codes for
      legitimate, within-limit callers.
      47 passed, 0 failed (after fixing a real self-inflicted test-isolation bug in this
      spec's own new rate-limit test — see `tasks.md` for the full story; no existing
      route's behavior actually changed).

## Constraints

- Python 3.12, `uv`-managed, `DocumentPortalException`-style error wrapping.
- Must not change `require_workspace_role`, JWT verification, or the RLS/workspace-filter
  isolation model — this spec adds policy around the existing auth path, not inside it.
- Rate-limit state must not require a new piece of infrastructure beyond what already runs
  locally (Redis is already required for Celery/Redis — reusing it for rate-limit counters is
  preferred over adding a new store, confirmed in `plan.md`).
- CORS allow-list must be configurable (env-driven), not hardcoded to one dev URL, so it
  works the same way in local dev and whatever `071` is eventually deployed to.
- Local dev/test must stay runnable the way `061` verified it (native Postgres/Keycloak/
  MinIO/Redis/Qdrant Cloud, native Jaeger/Prometheus/Grafana, `--pool=solo` Celery worker on
  Windows).

## Open questions

1. **Rate-limit scope and thresholds.** Per-authenticated-user, per-workspace, or per-API-key
   — and what numbers are defensible without real production traffic data to tune against?
   Leaning: per-(caller identity, route) using Redis, with conservative starting thresholds
   documented as "revisit once real usage exists," not derived from load testing that doesn't
   apply yet. → `plan.md`.
2. **CORS allow-list source.** A new `apps/api` setting (env var) listing allowed origins, or
   derived from where `071-search-frontend` actually gets deployed (not yet decided, since
   `071` hasn't been planned)? Leaning: a setting with a local-dev default (Vite's dev server
   origin), overridable per environment. → `plan.md`.
