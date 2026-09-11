# Tasks: Single-Tenant Simplification

- **Plan:** [plan.md](plan.md) (approved 2026-09-01)
- **Status:** done

Work top to bottom. Each group leaves the system runnable (import-clean + `tests/unit`
green). Integration suite is validated once at the end against real services.

## Group 1 — Schema + migration

- [x] Rewrite `packages/db/models.py`: delete `Tenant`, `TenantMember`, `UsageQuota` classes
      and `TENANT_SCOPED_TABLES`; remove the `tenant_id` column + its comment from
      `Workspace`, `WorkspaceMember`, `Document`, `DocumentVersion`, `IngestionJob`,
      `Conversation`, `Message`, `MessageFeedback`; change `ApiKey.tenant_id` →
      `workspace_id` (FK `workspaces`, `ondelete=CASCADE`, indexed); change
      `AuditLog.tenant_id` → `workspace_id` (nullable FK `workspaces`), rename its index to
      `ix_audit_log_workspace_id_created_at` — files: `packages/db/models.py` — verify:
      `python -c "import packages.db.models"`.
- [x] Replace the three migration files with one new `0001_initial_schema.py`
      (`down_revision = None`) creating the single-tenant schema directly: all kept tables,
      `users.auth_provider_subject` UNIQUE inline (was `0002`), no `tenant_id` columns, no
      `tenants`/`tenant_members`/`usage_quotas`, `api_keys.workspace_id`,
      `audit_log.workspace_id` nullable, the circular `documents.current_version_id` FK added
      after `document_versions`, **no RLS DDL**. `downgrade()` drops all tables FK-safe.
      Delete `0002_users_auth_provider_subject_unique.py` and
      `0003_workspace_members_tenant_id.py` — files:
      `packages/db/migrations/versions/*` — verify: fresh DB
      (`psql -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'`) then
      `uv run alembic upgrade head` then `uv run alembic downgrade base` both clean.
- [x] Update `packages/db/audit.py`: `write_audit_log(..., tenant_id)` →
      `workspace_id: uuid.UUID | None`; drop the RLS-GUC docstring note — files:
      `packages/db/audit.py` — verify: `python -c "import packages.db.audit"`.
- [x] Check `packages/db/__init__.py` / `config.py` for exports of removed names; remove any
      — files: `packages/db/__init__.py`, `packages/db/config.py` — verify:
      `python -c "import packages.db"`.

## Group 2 — Auth package

- [x] `packages/auth/context.py`: delete `resolve_tenant_role`, `set_tenant_scope`,
      `set_tenant_scope_sync`; `resolve_workspace_role` returns `str | None` (role only),
      drop the `tenant_id` from its select and docstring; keep `get_or_provision_user` —
      files: `packages/auth/context.py` — verify: `python -c "import packages.auth.context"`.
- [x] `packages/auth/rbac.py`: delete `_TENANT_ROLE_RANK` and `tenant_role_at_least` — files:
      `packages/auth/rbac.py` — verify: `uv run pytest tests/unit/test_auth_rbac.py` (after
      Group 6 test edit) / `python -c "import packages.auth.rbac"` now.
- [x] `packages/auth/api_keys.py`: drop the RLS/GUC docstring note from
      `resolve_active_api_key` (logic unchanged) — files: `packages/auth/api_keys.py` —
      verify: `python -c "import packages.auth.api_keys"`.
- [x] `packages/auth/jwt.py`: reword the line-19 comment ("tenant_id/role claim" → "scope/role
      claim") — files: `packages/auth/jwt.py` — verify: n/a (comment only).

## Group 3 — apps/api dependencies + app wiring

- [x] `apps/api/deps/rbac.py`: delete `TenantAccess` and `require_tenant_role`; drop
      `tenant_id` from `WorkspaceAccess`, make `user: User | None`; in
      `require_workspace_role` remove the `set_tenant_scope` call and adapt to
      `resolve_workspace_role` returning role-only; add an API-key branch — `is_api_key(token)`
      → `resolve_active_api_key`, reject if `None` or `api_key.workspace_id != workspace_id`,
      return `WorkspaceAccess(workspace_id, user=None, role="owner")` — files:
      `apps/api/deps/rbac.py` — verify: `python -c "import apps.api.deps.rbac"`.
- [x] `apps/api/deps/auth.py`: update `get_current_user` docstring (drop tenant framing) —
      files: `apps/api/deps/auth.py` — verify: import.
- [x] `apps/api/main.py`: remove `tenants` import and `include_router(tenants.router)` —
      files: `apps/api/main.py` — verify: `python -c "import apps.api.main"`.

## Group 4 — apps/api routers + schemas

- [x] Delete `apps/api/routers/tenants.py` and `apps/api/schemas/tenants.py`. Add
      `apps/api/schemas/workspaces.py` with `WorkspaceCreate` (`name`) and `WorkspaceOut`
      (`id`, `name`, `created_at` — no `tenant_id`) — files: as listed — verify: import.
- [x] `apps/api/routers/workspaces.py`: add `POST /workspaces` (dep `get_current_user`, any
      authed user → insert `Workspace` + `WorkspaceMember(role="owner")`, return
      `WorkspaceOut`) and `GET /workspaces` (list caller's workspaces via join on
      `workspace_members`). In the existing member routes drop `tenant_id=access.tenant_id`
      from `WorkspaceMember(...)` and pass `workspace_id=access.workspace_id` to
      `write_audit_log` — files: `apps/api/routers/workspaces.py` — verify: import;
      `app.openapi()` shows the two new routes.
- [x] Move api-key routes into `apps/api/routers/auth.py` (or a new
      `routers/api_keys.py`): prefix `/workspaces/{workspace_id}/api-keys`, guard
      `require_workspace_role("owner")`, `ApiKey(workspace_id=access.workspace_id, …)`,
      `write_audit_log(workspace_id=access.workspace_id, …)`, `list`/`revoke` filter by
      `ApiKey.workspace_id == access.workspace_id`; keep the `access.user is None` guard on
      create — files: `apps/api/routers/auth.py`, `apps/api/main.py` (router include) —
      verify: import; `app.openapi()`.
- [x] `apps/api/routers/documents.py`: drop `tenant_id=access.tenant_id` from `Document`,
      `DocumentVersion`, `IngestionJob`; `document_key(access.workspace_id, document.id,
      file_hash)`; `run_ingestion_job.delay(str(job.id))` (no tenant arg) — files:
      `apps/api/routers/documents.py` — verify: import.
- [x] `apps/api/routers/jobs.py`: replace `IngestionJob.tenant_id == access.tenant_id` with
      `select(IngestionJob).join(Document).where(IngestionJob.id == job_id,
      Document.workspace_id == access.workspace_id)` — files: `apps/api/routers/jobs.py` —
      verify: import.
- [x] Grep `apps/api/schemas/*.py` for a `tenant_id` field on any response model; remove
      (expected: only `WorkspaceOut`, handled above) — files: `apps/api/schemas/` — verify:
      `grep -rn tenant apps/api/schemas` empty.

## Group 5 — ingestion, workers, storage

- [x] `packages/storage/keys.py`: remove `tenant_id` param from `document_key` and
      `image_key`; keys become `{workspace_id}/{document_id}/…` — files:
      `packages/storage/keys.py` — verify: `uv run pytest tests/unit/test_storage_keys.py`
      (after Group 6).
- [x] `packages/ingestion/pipeline.py`: remove `tenant_id` param from `run_ingestion`; drop
      `"tenant_id": str(tenant_id)` from the point payload; `image_key(document.workspace_id,
      …)` — files: `packages/ingestion/pipeline.py` — verify: import;
      `uv run pytest tests/unit -k ingestion`.
- [x] `packages/ingestion/qdrant_setup.py`: remove `"tenant_id"` from
      `REQUIRED_PAYLOAD_INDEXES` — files: `packages/ingestion/qdrant_setup.py` — verify:
      import.
- [x] `workers/celery_app.py`: `run_ingestion_job(self, job_id)` — drop the `tenant_id`
      arg, the `set_tenant_scope_sync` import + call, and the `uuid.UUID(tenant_id)` line;
      call `run_ingestion(job_id=…, session=…, …)` without `tenant_id` — files:
      `workers/celery_app.py` — verify: `python -c "import workers.celery_app"`.

## Group 6 — Unit tests

- [x] `tests/unit/test_auth_rbac.py`: delete tenant-role cases; keep workspace-role — verify:
      `uv run pytest tests/unit/test_auth_rbac.py`.
- [x] `tests/unit/test_db_models.py`: drop `Tenant`/`TenantMember`/`UsageQuota` and
      `tenant_id`-column assertions; add `api_keys.workspace_id` / `audit_log.workspace_id` —
      verify: `uv run pytest tests/unit/test_db_models.py`.
- [x] `tests/unit/test_storage_keys.py`: expect the `{workspace_id}/{document_id}/…` shape —
      verify: `uv run pytest tests/unit/test_storage_keys.py`.
- [x] Full unit run — verify: `uv run pytest tests/unit` green with no live services.

## Group 7 — Integration tests

- [x] Delete `tests/integration/test_rls.py`, `test_rls_engagement.py`,
      `test_tenant_workspace_lifecycle.py` — verify: files gone.
- [x] `tests/integration/conftest.py`: reword the `db_engine` docstring (no RLS); confirm
      `upgrade head` / `downgrade base` work against the squashed migration — verify: fixture
      collects.
- [x] Rewrite `test_api_keys.py` for workspace-scoped keys: create via
      `POST /workspaces/{id}/api-keys` as owner; key authenticates a GET on its own
      workspace; rejected (`403`/`404`) on a different workspace; revoked key rejected —
      verify: `uv run pytest tests/integration/test_api_keys.py`.
- [x] Rewrite `test_audit_log.py` around `workspace_id` rows — verify: pytest that file.
- [x] Update `test_auth_flow.py`, `test_jit_provisioning.py`, `test_db_roundtrip.py`: drop
      tenant creation/paths; use `POST /workspaces` — verify: pytest those files.
- [x] Update `test_upload_and_ingest.py`, `test_versioning.py`, `test_ingestion_failure.py`,
      `test_document_routes_rbac.py`: setup is create-workspace (no tenant); assert Qdrant
      payload has `workspace_id` and **no** `tenant_id`; DB-row assertions drop `tenant_id` —
      verify: pytest those files against real Postgres/MinIO/Qdrant/Memurai/Keycloak + real
      `OPENAI_API_KEY`.
- [x] Full integration run — verify: `uv run pytest tests/integration` green against real
      services.

## Group 8 — Docs

- [x] `specs/architecture/02-data-model.md`: status banner → `012`; add "As-built
      (single-tenant)" subsection; mark the multi-tenant §2/§3/§4 body ⚠️ DEFERRED — verify:
      read-through.
- [x] `specs/architecture/06-security-model.md`: banner; §3 tenant level deferred; §4
      `workspace_id` sole mandatory filter dimension; §5 workspace isolation + RLS deferred;
      §7 audit by workspace owner — verify: read-through.
- [x] `specs/architecture/08-roadmap.md`: Phase 2 + Phase 4 notes; new **Phase 10 — Restore
      Multi-Tenancy** (`090-099`) row — verify: read-through.
- [x] Light touch: `01-system-architecture.md`, `03-ingestion-workflow.md`,
      `09-repo-and-module-structure.md` (endpoint inventory), `04-retrieval-design.md`,
      `07-evaluation-observability.md`, `CLAUDE.md` — verify:
      `grep -rn "tenant" specs/architecture CLAUDE.md` returns only intentional
      deferred-context prose.
- [x] `specs/README.md`: set `012` status → `done`; note `011` tenancy superseded — verify:
      read-through.

## Verification (end of increment)

- [x] Every acceptance criterion in `spec.md` satisfied and checked.
- [x] `grep -rn "tenant" packages/ apps/ workers/` returns nothing outside deliberate prose
      (no code identifiers, no columns, no params).
- [x] `uv run pytest tests/unit` passes with no live services.
- [x] `uv run pytest tests/integration` passes against real local Postgres/MinIO/Qdrant/
      Memurai/Keycloak + a real `OPENAI_API_KEY`.
- [x] `apps/api` `app.openapi()` has no `/tenants*` path and includes `POST /workspaces`,
      `GET /workspaces`, `/workspaces/{id}/api-keys`.
- [x] Architecture docs + `specs/README.md` updated per Group 8.
