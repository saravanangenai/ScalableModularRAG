# Tasks: Auth and Workspaces

- **Plan:** [plan.md](plan.md) (approved 2026-08-24)
- **Status:** done — 67/67 tests pass (49 unit, 18 integration) against real local Postgres 16
  + MinIO + Keycloak (native installs, not Docker).

Work top to bottom. Each group should leave the system in a runnable state. Check items off
with `- [x]` as completed; do not delete or renumber finished items.

Local verification uses native installs (no Docker in this environment, matching how `010`
was verified): PostgreSQL 16 + MinIO are already running from `010`; this spec adds a native
Keycloak (Quarkus distribution) instance the same way.

## Group 1 — Keycloak local setup + config

- [x] Install Keycloak (Quarkus distribution zip, no Docker) and start it in dev mode with a
      bootstrap admin user — files: none (local tooling, not repo-tracked) — verify: Keycloak
      26.7.2 running at `http://localhost:8080`, confirmed via HTTP.
- [x] `scripts/setup_keycloak_dev.py`: one-shot script using Keycloak's Admin REST API to
      create a `mm-rag` realm, a confidential client (`mm-rag-api`, with an audience mapper
      so tokens actually carry `aud: mm-rag-api`) with Direct Access Grants enabled (so tests
      can mint real tokens via the Resource Owner Password Credentials grant without a
      browser), and a test user with a known password — files:
      `scripts/setup_keycloak_dev.py` — verified: ran twice, second run is a clean no-op
      ("already exists" for all three, still updates `infra/.env`). End-to-end verified: real
      password-grant token from this realm passes `packages.auth.jwt.verify_token` against
      the live JWKS endpoint.
- [x] Add `KEYCLOAK_ISSUER_URL`, `KEYCLOAK_AUDIENCE` to `infra/.env.example` (runtime config
      for `apps/api`), plus a clearly-marked dev-only section for
      `KEYCLOAK_ADMIN`/`KEYCLOAK_ADMIN_PASSWORD`/`KEYCLOAK_TEST_CLIENT_SECRET` used only by
      the setup script and tests, never by `apps/api` itself — files: `infra/.env.example`.
- [x] Add a `keycloak` service block to `infra/docker-compose.yml` for parity/documentation
      (even though local verification here runs it natively) — files:
      `infra/docker-compose.yml` — added (`quay.io/keycloak/keycloak:26.7.2`, `start-dev`);
      not started via compose in this environment.

## Group 2 — `packages/exceptions` + `packages/auth` core

- [x] `packages/exceptions/auth.py`: `AuthenticationError` (401), `AuthorizationError` (403),
      `MembershipNotFoundError` (404) — files: `packages/exceptions/auth.py` — verify: unit
      test per exception type — **3 tests pass**.
- [x] `packages/auth/config.py`: `Settings` (`KEYCLOAK_ISSUER_URL`, `KEYCLOAK_AUDIENCE`) —
      files: `packages/auth/config.py` — verify: unit test — **passes**.
- [x] `packages/auth/jwt.py`: `verify_token(token) -> claims` using `PyJWT`'s `PyJWKClient`
      against the configured issuer's JWKS endpoint; checks signature/`exp`/`iss`/`aud`;
      raises `AuthenticationError` on any failure — files: `packages/auth/jwt.py` — verify:
      unit tests with a locally-generated RSA keypair covering valid/expired/wrong-issuer/
      wrong-audience/bad-signature — **5 tests pass** — plus manually verified end-to-end
      against the real live Keycloak JWKS endpoint with a real password-grant token.
- [x] `packages/auth/rbac.py`: role-ordering helpers (`tenant_role_at_least`,
      `workspace_role_at_least`) — files: `packages/auth/rbac.py` — verify: unit test table
      covering every role pair — **18 tests pass**.
- [x] `packages/auth/context.py`: `get_or_provision_user(session, sub, email,
      display_name)` (JIT provisioning, catches unique-violation race and re-queries),
      `resolve_tenant_role(session, user_id, tenant_id)`,
      `resolve_workspace_role(session, user_id, workspace_id)` (query
      `tenant_members`/`workspace_members` directly — no GUC needed, see plan.md "Bootstrap
      ordering"; returns `(role, tenant_id)` for the workspace case — see Group 3's
      `workspace_members.tenant_id` addition), `set_tenant_scope(session, tenant_id)`
      (`SELECT set_config(...)`) — files: `packages/auth/context.py` — verified by Group 6
      integration tests, including a genuine concurrent-first-request race test.
- [x] `packages/auth/api_keys.py` (added, not in original task breakdown): key
      generation/hashing (`mmrag_`-prefixed, sha256), `resolve_active_api_key` — needed
      because `api_keys` turned out to be RLS-protected, unlike the membership tables — see
      plan.md "API keys as an alternative credential" — files: `packages/auth/api_keys.py`.

## Group 3 — Schema fixes: unique `auth_provider_subject`, `workspace_members.tenant_id`

- [x] `packages/db/models.py`: `User.auth_provider_subject` gets `unique=True` — files:
      `packages/db/models.py` — verify: unit test (extended `test_db_models.py`) — **passes**.
- [x] Migration `0002_users_auth_provider_subject_unique.py`: `upgrade()` adds a unique
      constraint, `downgrade()` drops it — files:
      `packages/db/migrations/versions/0002_users_auth_provider_subject_unique.py` — verify:
      `alembic upgrade head` / `downgrade -1` / `upgrade head` round-tripped cleanly against
      real local Postgres.
- [x] `specs/architecture/02-data-model.md`: annotate `users.auth_provider_subject` as
      unique — files: `specs/architecture/02-data-model.md`.
- [x] `specs/architecture/06-security-model.md` §2: record Keycloak (self-hosted) as the
      chosen IdP per plan.md's architecture-doc delta — files:
      `specs/architecture/06-security-model.md`.
- [x] **(added, not in original task breakdown)** `packages/db/models.py`:
      `WorkspaceMember.tenant_id` denormalized column, plus migration
      `0003_workspace_members_tenant_id.py` (add nullable, backfill, set `NOT NULL`) — found
      while implementing `require_workspace_role`: resolving which tenant a `workspace_id`
      belongs to needs to happen before the RLS GUC is set, and `workspaces` itself is
      RLS-protected — see plan.md's Data model changes and `02-data-model.md`'s updated
      denormalization note. Verified: `alembic upgrade head` / `downgrade -1` / `upgrade
      head` round-tripped cleanly against real local Postgres.

## Group 4 — `apps/api` skeleton

- [x] `apps/api/main.py`: FastAPI app factory, `GET /health` (no auth) — files:
      `apps/api/main.py` — verify: started via `uvicorn`, `curl localhost:8000/health`
      returned `200 {"status":"ok"}`; also covered by an automated integration test.
- [x] `apps/api/deps/auth.py`: `get_current_user` (JWT-only — used by routes with no
      tenant/workspace in the path, e.g. create/list tenant) — files:
      `apps/api/deps/auth.py`.
- [x] `apps/api/deps/rbac.py`: `require_tenant_role(min_role)` (accepts JWT **or** an
      `mmrag_`-prefixed API key — see plan.md's "API keys as an alternative credential" for
      why that needed a different bootstrap path than plain role resolution),
      `require_workspace_role(min_role)` (JWT only — `api_keys` has no workspace granularity)
      — resolve role via `packages.auth.context`, raise
      `MembershipNotFoundError`/`AuthorizationError` as appropriate, call `set_tenant_scope`
      on success — files: `apps/api/deps/rbac.py` — verified end-to-end via manual curl
      against real Keycloak + Postgres, then via Group 6's automated suite.
- [x] `apps/api/main.py`: exception handlers mapping `AuthenticationError` -> `401`,
      `AuthorizationError` -> `403`, `MembershipNotFoundError` -> `404`, each with a generic
      body — files: `apps/api/main.py`.
- [x] `apps/api/schemas/`: pydantic request/response models — files:
      `apps/api/schemas/tenants.py`, `apps/api/schemas/members.py` (shared between tenant and
      workspace member routes — split out from the originally planned `tenants.py`/
      `workspaces.py` split since the shapes are identical), `apps/api/schemas/api_keys.py`.
- [x] `packages/db/audit.py` (added, not in original task breakdown): `write_audit_log(...)`
      helper shared by every mutating route — files: `packages/db/audit.py`.

## Group 5 — Routers

- [x] `apps/api/routers/tenants.py`: `POST /tenants`, `GET /tenants`, `POST
      /tenants/{tenant_id}/workspaces`, `GET /tenants/{tenant_id}/workspaces`, `POST|PATCH|DELETE
      /tenants/{tenant_id}/members[/{user_id}]` — files: `apps/api/routers/tenants.py` — note:
      `create_workspace` also inserts a `workspace_members` row (`role="owner"`) for the
      caller — see plan.md "Implementation findings" for why that was necessary, not optional.
- [x] `apps/api/routers/workspaces.py`: `POST|PATCH|DELETE
      /workspaces/{workspace_id}/members[/{user_id}]` — files:
      `apps/api/routers/workspaces.py`.
- [x] `apps/api/routers/auth.py`: `POST /tenants/{tenant_id}/api-keys`, `GET
      /tenants/{tenant_id}/api-keys`, `DELETE /tenants/{tenant_id}/api-keys/{id}` — files:
      `apps/api/routers/auth.py`.
- [x] Every mutating route writes one `audit_log` row in the same transaction — files: same
      as above — verified by `tests/integration/test_audit_log.py`.

## Group 6 — Integration tests (require real Postgres + Keycloak)

All of the below **ran and passed** against real local Postgres 16 + Keycloak 26.7.2 (native
installs, not Docker — this environment has no Docker; see Verification section).

- [x] `tests/integration/test_auth_flow.py`: health check needs no auth; no token -> `401`;
      garbage token -> `401`; valid token for a non-member tenant -> `404`; valid token for a
      member -> success. (Expired/wrong-issuer/wrong-audience/bad-signature are exercised
      against synthetic RSA tokens in `tests/unit/test_auth_jwt.py` instead of live Keycloak
      — waiting out a real token's 5-minute expiry isn't practical for a fast test suite, and
      the verification logic is identical either way.) — **4/4 passed**.
- [x] `tests/integration/test_tenant_workspace_lifecycle.py`: create tenant (caller becomes
      owner) -> create workspace (as tenant admin) -> member-role caller gets `403` creating a
      workspace but `200` listing them -> workspace-owner-only enforcement on workspace
      membership routes (`404` for a non-member, `201` for the owner) — **3/3 passed**. This
      is the test that caught the missing auto-workspace-membership bug (see plan.md).
- [x] `tests/integration/test_rls_engagement.py`: two tenants (owned by two different real
      users), a **raw SQL query with no `WHERE tenant_id` clause at all**, GUC set to tenant
      A — only tenant A's workspace is visible. Proves RLS itself, not just the router's
      app-level filter — **1/1 passed**.
- [x] `tests/integration/test_api_keys.py`: create key (plaintext returned once, `mmrag_`
      prefix) -> use it as a bearer credential -> using it against a different tenant is
      `401` (not distinguishing "wrong key" from "wrong tenant") -> revoke -> subsequent use
      `401`; list-keys response never includes the hash or plaintext — **2/2 passed**.
- [x] `tests/integration/test_audit_log.py`: tenant-member add/remove and api-key
      create/revoke produce exactly the expected 4 ordered `audit_log` rows with correct
      `action`/`resource_id` — **1/1 passed**.
- [x] `tests/integration/test_jit_provisioning.py`: first request from a genuinely fresh
      Keycloak identity (created via the Admin API mid-test, not the shared `testuser`)
      provisions exactly one `users` row; 5 concurrent first-requests for the same fresh
      identity still result in exactly one row — **2/2 passed**, real race exercised (not
      simulated).

## Verification (end of increment)

This environment has no Docker, so — per explicit user direction, same as `010` — local
verification used **native installs**: PostgreSQL 16 and MinIO were already running from
`010`; this spec added **Keycloak 26.7.2** via the standalone Quarkus distribution zip (no
installer, `bin/kc.bat start-dev`), bootstrapped with `scripts/setup_keycloak_dev.py`.

- [x] All acceptance criteria in `spec.md` satisfied and verified against real services.
- [x] `uv run pytest tests/unit` passes without any live services — 49 passed.
- [x] `uv run pytest tests/integration` passes against real local Postgres + Keycloak — 18
      passed (67 total with unit tests).
- [x] `specs/README.md` status for `011-auth-and-workspaces` updated to `done`.
- [x] `specs/architecture/06-security-model.md` and `02-data-model.md` deltas from plan.md
      applied (IdP choice recorded; `auth_provider_subject` and `workspace_members.tenant_id`
      documented).
