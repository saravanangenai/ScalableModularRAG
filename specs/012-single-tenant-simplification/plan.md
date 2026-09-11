# Plan: Single-Tenant Simplification

- **Spec:** [spec.md](spec.md) (approved 2026-09-01)
- **Status:** draft

## Summary

Purely subtractive change plus one small redesign. We delete the `tenants` /
`tenant_members` / `usage_quotas` tables, drop the denormalized `tenant_id` column from
every remaining table, remove all Row-Level Security DDL and the `app.current_tenant_id`
GUC plumbing, and delete the `/tenants*` routes and the tenant role ladder. Authentication
(IdP/JWT verification, JIT user provisioning) and the `workspaces` / `workspace_members`
owner/editor/viewer model are untouched as behaviour — they just stop being nested under a
tenant. Workspace creation moves to `POST /workspaces`, open to any authenticated user, who
becomes the new workspace's `owner`. `api_keys` and `audit_log` lose `tenant_id` and gain
`workspace_id`. The migration history is squashed to a single single-tenant baseline. The
multi-tenant design stays in the architecture docs, marked **deferred** with a new roadmap
row for restoring it.

## Architecture doc deltas

| Doc | Change |
|---|---|
| `02-data-model.md` | Status banner → points at `012`. New "As-built (single-tenant)" subsection giving the live schema: no `tenants`/`tenant_members`/`usage_quotas`, no `tenant_id` columns, `api_keys.workspace_id`, `audit_log.workspace_id` (nullable), no RLS. The existing multi-tenant body (§2 tables, §2 RLS paragraph, §3 `tenant_id` payload field + index, §4 ER summary) is kept but marked ⚠️ DEFERRED. |
| `06-security-model.md` | Status banner → `012`. §3: tenant role level marked deferred; workspace RBAC is the only live ladder. §4: retrieval-time filter contract updated so `workspace_id` is the **sole** mandatory, server-constructed dimension (no `tenant_id` term); everything else in §4 stands. §5: "tenant isolation" → "workspace isolation"; payload-partitioning and the indistinguishable-404 rule stay; Postgres RLS "defense in depth" marked deferred to Phase 4. §7: audit rows queryable by workspace `owner`+ for their workspace. |
| `08-roadmap.md` | Phase 2 row: note "tenancy simplified to single-tenant by `012`". Phase 4 row: retrieval filter is workspace-only. New row **Phase 10 — Restore Multi-Tenancy** (`090-099`), depends on Phase 8: re-introduce `tenants`/`tenant_members`, `tenant_id` denormalization + RLS, tenant-scoped quotas/keys/audit. |
| `01-system-architecture.md` | Prose "multi-tenant" mentions get a parenthetical "(single-tenant as-built, see `012`)". No diagram change. |
| `03-ingestion-workflow.md` | "tenant-scoped payload / key" → "workspace-scoped"; one-line note. |
| `09-repo-and-module-structure.md` | Endpoint inventory: remove `/tenants*`, `/tenants/{id}/workspaces`, `/tenants/{id}/members`, `/tenants/{id}/api-keys`; add `POST /workspaces`, `GET /workspaces`, `/workspaces/{id}/api-keys`. |
| `04-retrieval-design.md`, `07-evaluation-observability.md` | Grep hits are incidental "tenant" prose; a light touch to say workspace where it currently says tenant. No design change. |
| `CLAUDE.md` (not an architecture doc, but describes current state) | One line under Conventions: tenancy is single-tenant as-built per `specs/012`; `06-security-model.md` §6 secret rules unchanged. |

## Component/module ownership

No new module boundaries. Changes are confined to existing owners:

- `packages/db` — schema, models, migration, audit helper.
- `packages/auth` — drops tenant role/GUC helpers; workspace role resolution simplified.
- `apps/api` — router deletion/move, dependency simplification, API-key re-scope.
- `packages/ingestion` + `workers` — drop `tenant_id` from the pipeline signature and Qdrant payload.
- `packages/storage` — object-key shape.

## Data model changes

### Dropped

- Tables: `tenants`, `tenant_members`, `usage_quotas`.
- Column `tenant_id` from: `workspaces`, `workspace_members`, `documents`,
  `document_versions`, `ingestion_jobs`, `conversations`, `messages`, `message_feedback`.
- All `ENABLE/FORCE ROW LEVEL SECURITY` + `CREATE POLICY tenant_isolation` DDL, and the
  `TENANT_SCOPED_TABLES` constant in `models.py` and the migration.
- Indexes on every dropped `tenant_id` column.

### Changed

- `api_keys.tenant_id` (FK `tenants`, NOT NULL) → `api_keys.workspace_id` (FK `workspaces`
  `ON DELETE CASCADE`, NOT NULL), indexed.
- `audit_log.tenant_id` (FK `tenants`, NOT NULL) → `audit_log.workspace_id` (FK
  `workspaces` `ON DELETE CASCADE`, **nullable** — a handful of actions aren't
  workspace-scoped), index `ix_audit_log_tenant_id_created_at` →
  `ix_audit_log_workspace_id_created_at`.

### Kept as-is

`users` (with `auth_provider_subject` UNIQUE — folded into the new baseline from old
migration `0002`), `workspaces`, `workspace_members` (PK `(workspace_id, user_id)`, role
check constraint, `ix_workspace_members_user_id`), `documents`, `document_versions`,
`ingestion_jobs`, `conversations`, `messages`, `message_feedback`, and the circular
`documents.current_version_id` ↔ `document_versions.document_id` FK handled the same way.

### Migration approach — squash

Replace `0001_initial_schema.py`, `0002_users_auth_provider_subject_unique.py`,
`0003_workspace_members_tenant_id.py` with a **single new** `0001_initial_schema.py`
(`down_revision = None`) that creates the single-tenant schema directly. Delete `0002` and
`0003`. `downgrade()` drops every table in FK-safe order (no RLS teardown needed).

Rationale: these three migrations have only ever run against local/CI Postgres
(`tests/integration/conftest.py::db_engine` applies them per session and reverts to `base`).
Preserving a linear "add then drop" history would leave ~200 lines of dead tenant DDL and a
`downgrade()` that rebuilds a schema the code no longer supports. Squash is clean; the cost
(every dev recreates their local DB) is explicitly in-scope per the spec's non-goals.

Local reset for anyone with an existing dev DB:
`psql -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'` then `alembic upgrade head`.

### Qdrant / object storage

- Point payload drops `"tenant_id"`. `qdrant_setup.REQUIRED_PAYLOAD_INDEXES` drops the
  `tenant_id` keyword index.
- `packages/storage/keys.py`: `document_key(workspace_id, document_id, content_hash)` and
  `image_key(workspace_id, document_id, document_version_id, image_index)` — `tenant_id`
  parameter removed; keys become `{workspace_id}/{document_id}/…`.
- Existing local Qdrant collection and MinIO objects use the old shape — recreate the dev
  collection/bucket. Non-goal to migrate (spec).

## API contract

### Removed

| Method | Path |
|---|---|
| `POST` / `GET` | `/tenants` |
| `POST` / `GET` | `/tenants/{tenant_id}/workspaces` |
| `POST` / `PATCH` / `DELETE` | `/tenants/{tenant_id}/members[/{user_id}]` |
| `POST` / `GET` / `DELETE` | `/tenants/{tenant_id}/api-keys[/{key_id}]` |

### Added / moved

| Method | Path | Auth | Request | Response | Errors |
|---|---|---|---|---|---|
| `POST` | `/workspaces` | JWT (any authenticated user) | `{ "name": str }` | `201` `{ id, name, created_at }` | `401` |
| `GET` | `/workspaces` | JWT | — | `200` `[{ id, name, created_at }]` (only workspaces the caller is a member of) | `401` |
| `POST` | `/workspaces/{workspace_id}/api-keys` | JWT, workspace `owner` | `{ "scopes": [str] }` | `201` `{ id, key, scopes, created_at }` (plaintext `key` once) | `401`, `403`, `404` |
| `GET` | `/workspaces/{workspace_id}/api-keys` | JWT, workspace `owner` | — | `200` `[{ id, scopes, created_at, revoked_at }]` | `401`, `403`, `404` |
| `DELETE` | `/workspaces/{workspace_id}/api-keys/{key_id}` | JWT, workspace `owner` | — | `204` | `401`, `403`, `404` |

### Unchanged paths, internal simplification only

`/workspaces/{workspace_id}/members…`, `/workspaces/{workspace_id}/documents…`,
`/workspaces/{workspace_id}/jobs/{job_id}`, `/auth/*`, `/health` — same paths, same
status-code policy. Bodies drop any `tenant_id` field (none are currently exposed in
`DocumentOut`/`JobOut`/`WorkspaceOut` except `WorkspaceOut.tenant_id`, which is removed).

### Auth-dependency behaviour

- `require_tenant_role` and `TenantAccess` deleted.
- `WorkspaceAccess` loses its `tenant_id` field; `user` becomes `User | None`.
- `require_workspace_role(min_role)`:
  - Accepts a **JWT** (as today) → resolves `user`, workspace role from `workspace_members`;
    no GUC call.
  - Accepts an **API key** (`mmrag_` prefix) → resolves the key by hash, rejects if revoked
    or if `api_key.workspace_id != {workspace_id}` in the path; yields
    `WorkspaceAccess(user=None, role="owner")`.
  - Routes that attribute a write to a user (`upload_document` → `documents.created_by`,
    member management, api-key management) keep an explicit
    `if access.user is None: raise AuthenticationError(...)` — same pattern the deleted
    `create_tenant`/`create_api_key` used. Net effect: API keys are read-capable on
    workspace routes, not write-capable. Documented, not a bug.
- `get_current_user` (JWT → `User`, unchanged) now backs `POST /workspaces` and
  `GET /workspaces`; its docstring's tenant reference is updated.

## Retrieval / ingestion impact

Ingestion: `run_ingestion(job_id, *, session, storage, qdrant_client, …)` — `tenant_id`
parameter removed. Worker task `run_ingestion_job(job_id)` — `tenant_id` argument,
`set_tenant_scope_sync` import and call all removed (the worker session no longer needs a
GUC; `run_ingestion` already reads `document.workspace_id` for `image_key` and payload).
Point payload carries `workspace_id` and no `tenant_id`. No change to parsing, chunking,
embedding, latency, or cost.

Retrieval: no retrieval pipeline exists yet. This plan only fixes the **contract** Phase 4
will build to — `workspace_id` is the sole mandatory server-side filter dimension.

## Security / tenancy impact

This plan **does** touch auth and the isolation model. How isolation is preserved:

- **Authentication is unchanged and un-weakened.** Every non-health route still goes through
  `require_workspace_role` or `get_current_user`, both of which reject a missing/invalid JWT
  with `401` before any handler runs. No route becomes anonymous as a side effect.
- **Workspace isolation is still enforced in the query, not the UI.** Every document/job/
  member handler already filters by `Document.workspace_id == access.workspace_id` (or the
  equivalent join) after a `workspace_members` role check. That check is unchanged; only the
  tenant layer above it is gone. `jobs.get_job` switches from `IngestionJob.tenant_id ==`
  to a `join(Document).where(Document.workspace_id == access.workspace_id)`.
- **Loss: Postgres RLS as a second enforcement layer.** Removed with the tenant GUC it
  depended on. Mitigation: application-layer filtering above is the enforcement for this
  increment; Phase 4 owns re-adding defense-in-depth (workspace-scoped RLS and the mandatory
  Qdrant retrieval filter) with the retrieval-bypass threat model in focus. Recorded in
  `06-security-model.md` §5 as deferred, and in the Phase 4 roadmap row.
- **API-key scope shrinks, not grows** — from tenant-wide to a single workspace, read-only
  in practice. No key can reach a workspace it wasn't minted for (`workspace_id` equality
  check in the dependency).
- **Enumeration protection kept** — the indistinguishable `404` for "absent" vs. "forbidden"
  (`06-security-model.md` §5) still holds via the existing `MembershipNotFoundError` → `404`
  handler.

## Rollout

Big-bang on `master`. Pre-production, single developer, no external consumers, so no feature
flag (a schema squash can't be flag-gated meaningfully). Revert path: `git revert` the
implementation commit(s), then recreate the local DB / Qdrant collection from the restored
migration chain. `specs/README.md` status returns to `done` for `011` semantics.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| A `tenant_id` reference missed somewhere → `AttributeError`/SQL error at runtime | Med | Med | `grep -rn "tenant" packages/ apps/ workers/` must reduce to only intentional prose; full `pytest tests/unit` + `tests/integration` against real services before marking done |
| API-key re-scope is the one non-mechanical change; edge cases in the dependency branch | Med | Med | Keep it minimal (read-capable, owner-equivalent, `workspace_id` equality); one rewritten `test_api_keys.py` covering wrong-workspace + revoked |
| Squashed history confuses a future "restore multi-tenancy" effort | Low | Low | Phase 10 roadmap row + this plan document the squash explicitly; the deferred multi-tenant design stays in `02`/`06` |
| Stale local Qdrant/MinIO data with old payload/key shape yields confusing test failures | Med | Low | Documented recreate step in Data model changes; `conftest` already rebuilds Postgres per session |
| Integration tests that set up a tenant first now have no such fixture path | High | Low | Enumerated in Tasks — delete `test_rls*.py` + `test_tenant_workspace_lifecycle.py`, update the six upload/version/failure/rbac/audit/api-key tests |

## Alternatives considered

- **Additive `0004` drop-migration** instead of squash — preserves linear history but keeps
  ~200 lines of dead tenant DDL in `0001` and a `downgrade()` that rebuilds an unsupported
  schema. Rejected: the migrations never ran anywhere permanent.
- **Keep `tenant_id` columns, hardcode one sentinel tenant UUID** — smaller diff, but leaves
  the RLS/GUC plumbing and the tenant role ladder (the actual complexity to be shed) in
  place and still shows a `tenants` table. Rejected: doesn't meet the goal.
- **Drop API-key auth entirely until a later spec needs it** — less work, but the approved
  spec's acceptance criteria commit to workspace-scoped keys and the rubric names
  "Public/API access". Rejected by spec.
- **Add workspace-scoped RLS now** — more defense-in-depth, but net-new security design that
  belongs with Phase 4's retrieval-bypass threat model, not a subtractive increment.
  Deferred to Phase 4.
