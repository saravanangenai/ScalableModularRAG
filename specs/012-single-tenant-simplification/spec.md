# Spec: Single-Tenant Simplification

- **ID:** `012-single-tenant-simplification`
- **Roadmap phase:** [08-roadmap.md](../architecture/08-roadmap.md) Phase 2 — amends the auth
  half (`011-auth-and-workspaces`) and reshapes what Phase 4 (`030-039`) has to build.
- **Status:** draft
- **Owner:** Saravanan Shanmugam
- **Date:** 2026-09-01

## Problem statement

`010-metadata-db-and-object-storage` and `011-auth-and-workspaces` shipped a full
multi-tenant model: a `tenants` table, `tenant_members` with an owner/admin/member role
ladder, a denormalized `tenant_id` column on ten domain tables, Postgres Row-Level Security
policies on all of them keyed on an `app.current_tenant_id` session GUC, tenant-scoped
`api_keys`/`audit_log`/`usage_quotas`, and a per-request auth flow that resolves a
`(user, tenant, workspace)` triple and sets the GUC (`packages/auth/context.py`,
`apps/api/deps/rbac.py`, `apps/api/routers/tenants.py`). Every table in
[02-data-model.md](../architecture/02-data-model.md) and every isolation mechanism in
[06-security-model.md](../architecture/06-security-model.md) §3–§5 assumes this.

For the assignment timeline this is more moving parts than the remaining phases can afford
to build and test against. The deployment is effectively single-organization: one install,
one group of users, no cross-tenant billing or plan tiers. The `tenants` layer, its role
ladder, the GUC/RLS machinery, and the tenant-scoped quota tables are cost without payoff at
this scope — but **authenticated login and per-workspace access control are not**: they are
still the mechanism that keeps one user's documents out of another user's search results,
and Phase 4's retrieval-time authorization test still has to pass.

This spec removes the `tenant` concept while keeping IdP login, `users`, `workspaces`,
`workspace_members`, and the workspace owner/editor/viewer role ladder intact. The
multi-tenant design remains the documented long-term target — the architecture docs keep it,
annotated as deferred, with a roadmap entry for restoring it.

## Goals

- Remove the tenant concept end to end: no `tenants` / `tenant_members` tables, no
  `tenant_id` column on any domain table, no tenant role ladder, no tenant CRUD or
  membership endpoints, no `app.current_tenant_id` GUC and no RLS policies that depend on it.
- Keep authentication exactly as strict: every non-health route still requires a verified
  JWT from the configured IdP (signature, expiry, issuer/audience), and `users` rows are
  still just-in-time provisioned from the IdP `sub` claim.
- Keep `workspaces` and `workspace_members` as the unit of isolation. A workspace still has
  members with an `owner` / `editor` / `viewer` role, and every workspace-scoped route still
  declares the minimum role it needs and rejects callers below it before business logic runs.
- Any authenticated user can create a workspace and becomes its `owner`; workspace owners
  add/remove members and change their roles. This replaces the old "tenant admin creates
  workspaces" gate.
- Retrieval-time authorization (built later, in the reshaped Phase 4) filters search results
  by the caller's `workspace_id` membership set alone — a server-constructed, non-optional
  filter, with no `tenant_id` term. A request that names no workspace is rejected, never
  defaulted to "search everything" ([06-security-model.md](../architecture/06-security-model.md) §4
  still holds, minus the tenant dimension).
- `audit_log` still records every security-relevant action (workspace membership
  add/remove/role change, API key create/revoke, document upload/delete), keyed by
  workspace instead of tenant.
- Programmatic access via `api_keys` still works — scoped, hashed at rest, revocable — but
  scoped to a workspace rather than a tenant.
- `apps/api`, the async ingestion pipeline (`020`), and its integration tests all still run:
  upload → job → `ready` → workspace-scoped Qdrant payload, with `workspace_id` (and no
  `tenant_id`) in the payload and the DB rows.
- The architecture docs (`02`, `06`, `08`, and any others that lean on tenancy) are updated
  in the same session: multi-tenancy is marked as deferred with a pointer to this spec, and
  `08-roadmap.md` gains an entry for a future "restore multi-tenancy" increment.

## Non-goals

- **Not** removing or weakening authentication. Login is mandatory on every route exactly as
  before; this spec only removes the tenant layer *above* the workspace.
- **Not** removing workspaces or the workspace role ladder. Per-workspace RBAC is the
  isolation model this spec keeps.
- **Not** building the retrieval-time filter itself — that is still Phase 4 (`030-039`).
  This spec only fixes its contract to be workspace-only so Phase 4 builds the simpler thing.
- **Not** a production data migration. `010`/`011`/`020` have only ever run against local
  dev/test databases; existing rows do not need to be preserved across the schema change.
  The migration strategy (squash vs. additive down-migration) is a `plan.md` decision.
- **Not** touching `packages/parsing` / `packages/ingestion` / `packages/retrieval` /
  `packages/generation` retrieval or parsing logic beyond dropping the `tenant_id` field
  from the metadata/payload they read and write.
- **Not** keeping `usage_quotas` (per-tenant by definition, unused, Phase 9 territory) — it
  is dropped here and re-introduced whenever billing (`080-089`) is specced.
- **Not** rewriting the architecture docs to abandon multi-tenancy as the eventual target —
  they keep the multi-tenant design, annotated as deferred.
- **Not** deleting the IdP itself or changing which IdP is used — Keycloak/JWT wiring from
  `011` stays.

## User-facing behavior

No end-user UI yet; observable behavior is at the API-consumer level.

- A client with a valid JWT calls `apps/api` and operates on workspaces it belongs to. There
  is no longer any `/tenants` route, no "create a tenant" step, and no tenant path segment
  or header — a request identifies a workspace directly.
- First-time flow for a new authenticated user: create a workspace (becomes its `owner`) →
  add other users to it with a role → upload documents (`editor`+) → ask questions
  (`viewer`+). No tenant provisioning precedes this.
- A client with no JWT, or an invalid/expired/wrong-issuer JWT, gets `401`. A client
  authenticated but not a member of the target workspace, or a member whose role is below
  what the route requires, gets `403`. A request for a workspace/resource that does not
  exist and one for a resource that exists but the caller cannot see are indistinguishable
  (`404`), so IDs cannot be enumerated
  ([06-security-model.md](../architecture/06-security-model.md) §5, minus the tenant angle).
- API-key auth: a workspace `owner` issues a key scoped to that workspace; the plaintext is
  returned once at creation and never again; a request using a revoked key is rejected.
- Existing `020` behavior is unchanged from the consumer's side: authenticated upload →
  `202` + job id → poll job status → `ready`, with results retrievable only within the
  owning workspace.

## Acceptance criteria

- [ ] The database schema has no `tenants` table, no `tenant_members` table, no `tenant_id`
      column on any remaining table, and no `usage_quotas` table. `packages/db/models.py`
      and [02-data-model.md](../architecture/02-data-model.md) agree with the migrated DB.
- [ ] No Row-Level Security policy referencing `app.current_tenant_id` exists in the
      migrated database; no code path calls `set_config('app.current_tenant_id', ...)`.
- [ ] `apps/api` exposes no `/tenants*` routes. `app.openapi()` contains workspace,
      document, job, and auth/API-key routes only.
- [ ] Every non-health route still returns `401` for a missing/invalid/expired/wrong-issuer
      JWT.
- [ ] A valid-JWT caller who is not a member of the target workspace gets `403`; a `viewer`
      calling an `editor`+ route gets `403`.
- [ ] Any authenticated user can create a workspace and is inserted into `workspace_members`
      as `owner` for it.
- [ ] A workspace `owner` can add an existing user to that workspace with a role, change
      that role, and remove the member; each writes exactly one `audit_log` row naming the
      actor, action, and affected resource.
- [ ] A workspace `owner` can create an API key scoped to that workspace; the plaintext is
      returned exactly once; a request authenticated with a since-revoked key is rejected.
- [ ] The `020` integration suite (`test_upload_and_ingest`, `test_versioning`,
      `test_ingestion_failure`, `test_document_routes_rbac`) passes against real
      Postgres/MinIO/Qdrant/Memurai/Keycloak + a real `OPENAI_API_KEY`, with `workspace_id`
      and no `tenant_id` in both the DB rows and the Qdrant point payloads.
- [ ] `uv run pytest tests/unit` passes with no live services.
- [ ] An authorization test asserts: user A's request against a workspace user A does not
      belong to returns `403`/`404`, never a filtered-but-`200` response.
- [ ] `02-data-model.md`, `06-security-model.md`, and `08-roadmap.md` are updated — tenancy
      marked deferred with a pointer here, and a roadmap row exists for restoring it.
      `specs/README.md` has a `012` row.
- [ ] `apps/api` still never holds or forwards provider API keys (OpenAI/Qdrant/reranker).

## Constraints

- Authentication strictness must not regress: no route becomes reachable without a valid JWT
  as a side effect of removing the tenant layer.
- Workspace isolation must remain a real boundary, not a UI convenience — the Phase 4
  retrieval filter contract in `06-security-model.md` §4 stays in force with `workspace_id`
  as the sole mandatory dimension.
- `010`/`011`/`020` are treated as amendable: any of their code, migrations, specs, or
  plan docs may change. Once implementation starts, though, this spec's scope is frozen —
  further tenancy changes are a new spec.
- Python 3.12, `uv`-managed. `packages/auth`/`packages/db` keep wrapping failures as
  `DocumentPortalException`-style exceptions from `packages/exceptions`.
- Local dev/test must stay runnable the way `020` verified it (native Postgres/MinIO/Qdrant/
  Memurai/Keycloak, no Docker requirement).
- The multi-tenant architecture docs are edited, not deleted — a future increment restores
  tenancy on top of this.

## Open questions

1. **Migration shape.** Since `010`/`011`/`020` only ever ran locally, is it acceptable to
   **squash** migrations `0001`–`0003` into a single new single-tenant baseline (cleaner
   history, but anyone with a local DB re-creates it), or should this be an **additive**
   `0004` that drops the tenant objects (preserves linear history, keeps a messy down-path)?
   Leaning squash. → `plan.md`.
2. **Defense-in-depth RLS.** The tenant RLS is removed. Do we (a) ship this increment with
   application-layer workspace filtering as the only enforcement and leave RLS-on-
   `workspace_id` to Phase 4, or (b) add workspace-scoped RLS policies now as part of this
   spec? Leaning (a) — keep this increment purely subtractive. → `plan.md`.
3. **API-key granularity.** `06-security-model.md` §2 and the current `require_workspace_role`
   note that "API keys have no workspace granularity in this data model." Re-scoping
   `api_keys` to a workspace is a small schema change but touches the auth middleware. Confirm
   workspace-scoped keys are wanted here vs. dropping API-key auth entirely until a later
   spec needs it.
4. **`audit_log` without a tenant.** With no tenant, `audit_log` is install-global. Keep it
   as a flat global table (queryable by any authenticated user? by workspace owners for their
   workspace's rows only?), or add a nullable `workspace_id` and scope reads to workspace
   owners? Leaning: add `workspace_id`, scope reads to workspace `owner`+. → `plan.md`.
