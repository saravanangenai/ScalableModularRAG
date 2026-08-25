# Plan: Auth and Workspaces

- **Spec:** [spec.md](spec.md) (approved 2026-08-24)
- **Status:** approved (2026-08-24)

## Summary

Stand up `apps/api` (FastAPI, first HTTP service in this repo) and `packages/auth`
(JWT verification against a self-hosted Keycloak realm + RBAC guards), backed entirely by
the `packages/db` schema from `010`. Every route resolves the caller's identity from a
verified JWT, re-derives their tenant/workspace role from `tenant_members`/
`workspace_members` (never from the token), sets the `app.current_tenant_id` Postgres GUC for
that request's session so `010`'s Row-Level Security policies actually engage, and rejects
anything outside that resolved scope with 401/403/404. Ships tenant/workspace/membership
management and API-key issuance — no document/chat/ingestion routes yet.

## Architecture doc deltas

| Doc | Change |
|---|---|
| `06-security-model.md` §2 | Currently says "Keycloak (self-hosted)... or Auth0/Clerk (managed)... pick one per deployment target." This plan resolves that choice for the project: **Keycloak, self-hosted**, chosen for full local-dev control, no external account/cost, and to keep local dev Docker-free-capable the same way `010` used native Postgres/MinIO installs instead of `infra/docker-compose.yml`. Doc updated to state this as the chosen IdP rather than an open choice. |
| `02-data-model.md` | `users.auth_provider_subject` is documented but was never marked unique in `02` or enforced in `packages/db/models.py` — a real gap, since it's the stable identity key JIT user-provisioning looks up by. Adding `UNIQUE` to `02-data-model.md`'s `users` entity and to the model/migration (see Data model changes). |
| `09-repo-and-module-structure.md` | No change needed — `apps/api/routers/auth.py` ("token exchange / api-key management") already anticipated API-key management living there; this spec implements the api-key half only (token exchange is Keycloak's own token endpoint, not proxied by `apps/api`). Adds `routers/tenants.py`, `routers/workspaces.py` (not previously listed, since `09`'s router table only covered post-Phase-2 document/chat routes) — noting here rather than editing `09`, since its table is explicitly "indicative." |

## Component/module ownership

- **`apps/api`** (new — first real code here)
  - `main.py` — FastAPI app factory, router registration, health check (`GET /health`, no auth).
  - `routers/tenants.py` — create tenant, list caller's tenants, create workspace under a
    tenant, list workspaces in a tenant, tenant membership add/remove/role-change.
  - `routers/workspaces.py` — workspace membership add/remove/role-change.
  - `routers/auth.py` — API key create/list/revoke (per `09`'s existing naming).
  - `deps/` — FastAPI dependencies: `get_current_user`, `require_tenant_role(min_role)`,
    `require_workspace_role(min_role)`, `get_db_session` (opens the async session and sets
    the RLS GUC once role resolution succeeds).
  - `schemas/` — pydantic request/response models per endpoint.
- **`packages/auth`** (new)
  - `jwt.py` — verifies a bearer token against Keycloak's JWKS (signature, `exp`, `iss`,
    `aud`); wraps failures as `AuthenticationError`.
  - `context.py` — resolves `(user, tenant_role, workspace_role)` from `packages/db` given a
    verified token's `sub` and a requested tenant/workspace id; JIT-provisions a `users` row
    on first sight of a new `sub`.
  - `rbac.py` — role-ordering helpers (`owner > admin > member`, `owner > editor > viewer`)
    used by the `require_*_role` dependencies.
  - `config.py` — `Settings` (`pydantic-settings`): `KEYCLOAK_ISSUER_URL`,
    `KEYCLOAK_AUDIENCE`.
- **`packages/exceptions`** — add `auth.py`: `AuthenticationError` (maps to `401`),
  `AuthorizationError` (maps to `403`) — both `DocumentPortalException` subclasses, same
  convention as `DatabaseError`/`ObjectStorageError`.
- **`packages/db`** — one additive migration (unique constraint), no other changes; reuses
  `010`'s async session factory as-is.
- No changes to `packages/ingestion`/`retrieval`/`generation`/`parsing`, `apps/UI`,
  `apps/streamlit-admin`.

## Data model changes

- **New migration `0002_users_auth_provider_subject_unique.py`**: adds a unique constraint on
  `users.auth_provider_subject`. `upgrade()` adds `UNIQUE`; `downgrade()` drops it. This is
  additive (no existing data, no backfill needed) and closes a real correctness gap: JIT
  provisioning looks up `users` by `auth_provider_subject`, and without a DB-level unique
  constraint, a race between two concurrent first-requests for the same new Keycloak subject
  could create two `users` rows for the same identity.
- `packages/db/models.py`: `User.auth_provider_subject` gets `unique=True`.
- `specs/architecture/02-data-model.md`: `users.auth_provider_subject` entry annotated
  `-- unique, maps to the IdP's sub claim`.
- **New migration `0003_workspace_members_tenant_id.py`** (found while implementing, not
  anticipated when this plan was first drafted): adds a denormalized `tenant_id` column to
  `workspace_members`, populated at insert time from the parent workspace's `tenant_id` —
  same pattern `010` already used for `documents`/`conversations`/etc. **Why**:
  workspace-scoped requests need to know which tenant a `workspace_id` belongs to in order to
  set the `app.current_tenant_id` GUC correctly — but `workspaces` itself is RLS-protected, so
  looking that up via `SELECT tenant_id FROM workspaces WHERE id = ...` returns nothing before
  the GUC is set. `workspace_members` is (deliberately) not RLS-protected, exactly like
  `tenant_members`, so putting `tenant_id` there too resolves both "what's this caller's
  workspace role" and "what tenant do I scope the GUC to" in one bootstrap-safe query.
  `workspace_members` remains excluded from `TENANT_SCOPED_TABLES`/RLS despite now carrying a
  `tenant_id` column — that exclusion is what makes it queryable pre-GUC in the first place.
- No other schema changes — `tenant_members.role`, `api_keys`, `audit_log` are already shaped
  correctly from `010`.

## API contract

All routes below require a verified JWT (`Authorization: Bearer <token>`) except `/health`.
`{tenant_id}`/`{workspace_id}` are path params; the caller's role for that id is resolved
server-side from `tenant_members`/`workspace_members`, never trusted from the token.

| Method & path | Auth | Body (request) | Success | Failure modes |
|---|---|---|---|---|
| `GET /health` | none | — | `200 {"status": "ok"}` | — |
| `POST /tenants` | any verified user | `{name, slug}` | `201`, caller becomes `owner` in `tenant_members` | `401` |
| `GET /tenants` | any verified user | — | `200 [ ]` — tenants the caller belongs to (app-level filter on `tenant_members.user_id`, not RLS — `tenants` itself carries no `tenant_id`) | `401` |
| `POST /tenants/{tenant_id}/workspaces` | tenant `admin`+ | `{name}` | `201` | `401`/`403`(insufficient role, is a member)/`404`(not a member) |
| `GET /tenants/{tenant_id}/workspaces` | tenant `member`+ | — | `200 [ ]` (RLS-scoped once GUC is set) | `401`/`404` |
| `POST /tenants/{tenant_id}/members` | tenant `admin`+ | `{user_id, role}` | `201`, writes `audit_log` | `401`/`403`/`404` |
| `PATCH /tenants/{tenant_id}/members/{user_id}` | tenant `admin`+ | `{role}` | `200`, writes `audit_log` | `401`/`403`/`404` |
| `DELETE /tenants/{tenant_id}/members/{user_id}` | tenant `admin`+ | — | `204`, writes `audit_log` | `401`/`403`/`404` |
| `POST /workspaces/{workspace_id}/members` | workspace `owner` | `{user_id, role}` | `201`, writes `audit_log` | `401`/`403`/`404` |
| `PATCH /workspaces/{workspace_id}/members/{user_id}` | workspace `owner` | `{role}` | `200`, writes `audit_log` | `401`/`403`/`404` |
| `DELETE /workspaces/{workspace_id}/members/{user_id}` | workspace `owner` | — | `204`, writes `audit_log` | `401`/`403`/`404` |
| `POST /tenants/{tenant_id}/api-keys` | tenant `admin`+ | `{scopes}` | `201 {id, key}` — plaintext `key` returned **once**, only `key_hash` persisted | `401`/`403`/`404` |
| `GET /tenants/{tenant_id}/api-keys` | tenant `admin`+ | — | `200 [ ]` — never includes `key_hash` or plaintext | `401`/`403`/`404` |
| `DELETE /tenants/{tenant_id}/api-keys/{id}` | tenant `admin`+ | — | `204`, sets `revoked_at`, writes `audit_log` | `401`/`403`/`404` |

**401 vs 403 vs 404 policy** (resolves spec's "indistinguishable 404" requirement precisely):
caller has **no membership at all** in the target tenant/workspace -> `404` (doesn't confirm
or deny the resource's existence to a non-member). Caller **is a member but lacks the
required role** -> `403` (they already know the resource exists; this doesn't leak anything
new). This mapping is centralized in one FastAPI exception handler translating
`AuthenticationError`/`AuthorizationError`/a `NotAMemberError` from `packages/auth`, so
individual route handlers can't accidentally diverge from it.

## Retrieval / ingestion impact

None. No `packages/retrieval`/`packages/ingestion`/`packages/generation` code touched, per
spec Non-goals.

## Security / tenancy impact

This spec **is** the security wiring `010` deferred. Concretely:

- **JWT verification**: `packages/auth/jwt.py` uses `PyJWT`'s `PyJWKClient` pointed at
  Keycloak's realm JWKS endpoint (`{KEYCLOAK_ISSUER_URL}/protocol/openid-connect/certs`),
  cached with its built-in TTL/reuse behavior. Verifies signature (RS256), `exp`, `iss`
  (must equal `KEYCLOAK_ISSUER_URL`), `aud` (must include `KEYCLOAK_AUDIENCE`). A token that
  fails any check raises `AuthenticationError` -> `401`. The `tenant_id`/role claims, if
  present in the token at all, are never read — only `sub` is used, per `06-security-model.md`
  §2 and this spec's Constraints.
- **JIT user provisioning**: on first successful verification of a new `sub`, `packages/auth`
  creates a `users` row (`email`/`display_name` from the token's `email`/`name` claims,
  `auth_provider_subject = sub`). The new unique constraint (see Data model changes) makes a
  concurrent double-provision race safe: the losing insert hits a unique-violation, and the
  code re-queries by `auth_provider_subject` instead of erroring.
- **Bootstrap ordering (why this doesn't deadlock)**: `tenant_members` and `workspace_members`
  are **not** RLS-protected tables in `010`'s migration (they carry no `tenant_id` column and
  were deliberately excluded from `TENANT_SCOPED_TABLES`) — this is what makes role
  resolution possible *before* the GUC is set. The request flow is: (1) verify JWT, resolve
  `users` row; (2) query `tenant_members`/`workspace_members` directly (no GUC needed) to
  determine the caller's role for the requested tenant/workspace; (3) if role is sufficient,
  `SELECT set_config('app.current_tenant_id', :tenant_id, true)` on that request's session;
  (4) only then run the route's actual (RLS-protected) queries.
- **RLS actually engages for the first time**: every route that reads/writes a
  `TENANT_SCOPED_TABLES` table now does so only after step 3 above — this is the acceptance
  criterion from `010`'s plan.md ("`011`'s plan must reference this exact GUC name") being
  fulfilled.
- **API keys as an alternative credential — and why they need a different bootstrap path than
  `tenant_members`/`workspace_members`**: `apps/api/deps/rbac.py`'s `require_tenant_role`
  also accepts `Authorization: Bearer <api_key>` — detected by a fixed prefix (`mmrag_`) so it
  never collides with a JWT. Unlike `tenant_members`/`workspace_members`, **`api_keys` *is* an
  RLS-protected table** (it's in `TENANT_SCOPED_TABLES`) — so a plain "look up by hash to
  discover which tenant this key belongs to" query is impossible before the GUC is set (that
  query would always return zero rows under `FORCE ROW LEVEL SECURITY`). Found while
  implementing, not anticipated when this plan was first written. Resolved without a schema
  change, using the fact that every route an API key can call already has `{tenant_id}` in
  its path: (1) tentatively `set_config` the GUC to the **path's** `tenant_id` (a client
  claim, not yet trusted); (2) query `api_keys` for that hash with `revoked_at IS NULL` — RLS
  means this can only return a row if the key **actually belongs** to that claimed tenant; (3)
  a match confirms the claim and grants that request tenant `admin`-equivalent scope; no match
  -> `401` (deliberately not distinguishing "wrong key" from "right key, wrong tenant" from
  "revoked" — all are just "invalid credential," nothing further is leaked). If the request
  handler raises before commit, the transaction (and its `SET LOCAL`-style GUC) never persists
  beyond that request. API keys are therefore only usable against tenant-path-scoped routes —
  every API-key-eligible endpoint in this spec's contract already has `tenant_id` in its path,
  so nothing in the contract needed to change. Workspace-scoped routes
  (`require_workspace_role`) don't accept API keys at all — `api_keys` has no workspace
  granularity in `02-data-model.md`, so this is a real (not accidental) scope limit.
- **Audit logging**: every mutation above writes one `audit_log` row (`actor_user_id`,
  `tenant_id`, `action`, `resource_type`, `resource_id`, `metadata_json`) in the same
  transaction as the mutation, after the GUC is already set (so the insert itself passes RLS).

## Rollout

No feature flag — this is the first traffic `apps/api` will ever serve, so there is nothing
to regress. Rollout is "stand up Keycloak, run `alembic upgrade head` (now including `0002`),
start `apps/api`." Revert is "don't deploy/start `apps/api`" — no other code depends on it yet.

## Implementation findings

Two more gaps were found only by running the real integration suite against real Postgres +
Keycloak — not anticipated when this plan was first drafted, consistent with how `010` found
its `FORCE ROW LEVEL SECURITY`/`NULLIF` gaps the same way:

- **Workspace creation didn't add the creator as a workspace member.** `POST
  /tenants/{tenant_id}/workspaces` (tenant `admin`+) created the `workspaces` row but nothing
  inserted a matching `workspace_members` row for the caller. Since `require_workspace_role`
  is the *only* thing that grants workspace-scoped access, and tenant-admin status doesn't
  imply workspace membership, this meant a newly created workspace was immediately
  unmanageable by anyone — not even its creator could add the first real member. Fixed in
  `apps/api/routers/tenants.py::create_workspace`: it now also inserts a `workspace_members`
  row for the caller with `role="owner"`, mirroring how tenant creation already auto-adds the
  creator as tenant owner. Caught by
  `tests/integration/test_tenant_workspace_lifecycle.py::test_workspace_owner_can_add_member_others_cannot`.
- **Ad-hoc test Keycloak users need `firstName`/`lastName`.** Not a production bug — Keycloak's
  declarative User Profile (default since Keycloak 24+) implicitly requires those attributes;
  a user created without them fails the Resource Owner Password Credentials grant with
  `"Account is not fully set up"`. `scripts/setup_keycloak_dev.py`'s users already set them;
  `tests/integration/conftest.py`'s `create_keycloak_user` factory (for JIT-provisioning
  tests needing a fresh identity) didn't, and now does.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| JWKS endpoint unreachable at request time makes all auth fail | Low locally, Medium in a real deploy | High (total outage) | `PyJWKClient` caches keys; failures surface as `401` with a generic message, not a `500` or leaked internals |
| `tenant_members`/`workspace_members` have no RLS (by design, for bootstrap ordering — see above) — a bug in a role-check query's `WHERE` clause could leak membership rows across tenants | Low | High | Dedicated unit + integration tests assert every role-check query filters by both `user_id` and `tenant_id`/`workspace_id`; this is the one place in the codebase where a missing filter has no RLS safety net |
| Local Keycloak setup is real operational complexity even without Docker (JVM-based, realm/client/test-user bootstrap) | Medium | Low (one-time local setup cost) | One setup script (`scripts/setup_keycloak_dev.py` or shell equivalent) creates the dev realm/client/test users via Keycloak's Admin REST API, documented step-by-step in `tasks.md`, mirroring how `010` documented native Postgres/MinIO setup |
| 404-vs-403 policy applied inconsistently across hand-written route handlers | Medium | Medium (info leak or confusing API) | Centralized in one exception-to-HTTP-status mapping (FastAPI exception handlers), not left to each route |
| JIT provisioning double-insert race on the same `sub` | Low | Low (would 500 without the fix) | Unique constraint + catch-and-requery, see Data model changes |

## Alternatives considered

- **Managed IdP (Auth0/Clerk)** — considered; rejected for now per explicit choice: no
  external account/cost dependency, works fully offline, consistent with this project's
  Docker-free local-dev direction from `010`.
- **Trusting a `tenant_id`/role claim embedded directly in the JWT** (Keycloak supports custom
  protocol mappers for this) — rejected per `06-security-model.md` §2: a claim baked in at
  token-issue time can be stale if membership changes before the token expires, especially
  with Keycloak's dev-mode tokens defaulting to longer lifetimes.
- **Storing API keys reversibly (encrypted, not hashed)** — rejected; matches `02-data-model.md`
  (`key_hash`) and `06-security-model.md` §6 ("hashed, never reversible") as already decided.
- **Skipping the `auth_provider_subject` unique constraint fix** (treat as out of scope for
  this spec) — rejected: JIT provisioning is introduced by *this* spec and is exactly what
  makes the missing constraint an active bug rather than a theoretical one; fixing it here is
  cheaper than a follow-up spec.
