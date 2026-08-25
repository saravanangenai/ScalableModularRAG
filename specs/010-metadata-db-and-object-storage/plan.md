# Plan: Metadata DB and Object Storage

- **Spec:** [spec.md](spec.md) (approved 2026-08-22)
- **Status:** approved (2026-08-23)

## Summary

Stand up `packages/db` (SQLAlchemy 2.x models + Alembic migrations against PostgreSQL, with
both sync and async engines so it works from FastAPI later and Celery workers later without
redesign), `packages/storage` (a generic S3-compatible client wrapping `boto3`, pointed at
MinIO locally), and `packages/exceptions` (a small typed exception hierarchy these two wrap
into). Nothing here is reachable over HTTP — it's a library layer, verified by integration
tests that run against the `postgres`/`minio` services in `infra/docker-compose.yml`.

## Architecture doc deltas

| Doc | Change |
|---|---|
| `02-data-model.md` | Denormalize `tenant_id` onto `documents`, `document_versions`, `ingestion_jobs`, `conversations`, `messages`, `message_feedback` — currently these only reach `tenant_id` transitively via `workspace_id`/`document_id`/`conversation_id` joins. Adding the direct column keeps Row-Level Security policies a single indexed equality check instead of a multi-level subquery on every row access. The column is redundant with the join path (denormalization, not a new relationship) and is populated at insert time from the parent workspace's `tenant_id` — never independently settable. |

No other architecture docs change. This spec doesn't touch retrieval, ingestion orchestration,
or the API contract.

## Component/module ownership

- **`packages/db`** (new) — SQLAlchemy declarative models (`models.py`), sync + async
  session factories (`session.py`), Alembic environment and migrations
  (`migrations/`), a `Settings` class (`config.py`, `pydantic-settings`) reading DB
  connection info from env vars.
- **`packages/storage`** (new) — `client.py` (upload/download/delete/exists against an
  S3-compatible endpoint), `config.py` (`pydantic-settings`, endpoint/bucket/credentials from
  env vars), `keys.py` (content-hash-addressed key scheme).
- **`packages/exceptions`** (new, minimal) — `base.py` (`DocumentPortalException`, matching
  the prototype's naming convention per `CLAUDE.md`), `db.py` (`DatabaseError`), `storage.py`
  (`ObjectStorageError`). No logging in this package — it only defines exception types.
- No other package or app is touched.

## Data model changes

All tables from `02-data-model.md` §2, plus the denormalized `tenant_id` columns described
above. Concretely, in addition to what's already documented:

- `documents.tenant_id`, `document_versions.tenant_id`, `ingestion_jobs.tenant_id`,
  `conversations.tenant_id`, `messages.tenant_id`, `message_feedback.tenant_id` — all
  `NOT NULL`, indexed, set at insert time from the parent's `tenant_id` (application-level
  responsibility; enforced additionally by a `CHECK`-free approach since Postgres can't easily
  check cross-table consistency — a future spec's authorization test suite is what actually
  proves this stays consistent once writes exist).
- Row-Level Security: every tenant-scoped table gets `ALTER TABLE ... ENABLE ROW LEVEL
  SECURITY`, `ALTER TABLE ... FORCE ROW LEVEL SECURITY`, and a policy `USING (tenant_id =
  NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)`. The session GUC
  `app.current_tenant_id` is not set by anything yet in this spec — no caller exists — so
  today these policies simply mean "no tenant ID set -> zero rows visible" for any session
  that doesn't set it (fails closed, which is the safe default; `011-auth-and-workspaces` is
  what sets the GUC per request).
  - **`FORCE ROW LEVEL SECURITY` is required**, not optional: Postgres exempts a table's
    *owner* from RLS by default, and the role that runs migrations locally owns the tables it
    creates. Without `FORCE`, "GUC unset -> zero rows" silently would not hold for that role.
    Found and fixed while verifying against a real local Postgres install.
  - **`NULLIF(..., '')` is required**, not `current_setting(..., true)::uuid` alone: a custom
    GUC's post-transaction reset value is an empty string `''`, not `NULL`, once it has been
    set at least once on a given backend connection — `current_setting(..., true)` only
    returns `NULL` if the GUC was *never* set on that connection. Under connection pooling
    (the norm once `011` and `apps/api` exist), a pooled connection that served an earlier
    request with the GUC set would otherwise throw `invalid input syntax for type uuid` on a
    later request that forgets to set it, instead of cleanly denying access. `NULLIF` folds
    both the never-set and reset-to-empty cases to `NULL`, so the row comparison is `NULL`
    (denied) either way. Found via `tests/integration/test_rls.py` against a real Postgres.
- Migration approach: one initial Alembic migration creating every table, index, and RLS
  policy from scratch (nothing exists today, so there's no backfill). Each migration provides
  `upgrade()` and `downgrade()`; `downgrade()` drops policies and disables RLS before dropping
  tables.

## API contract

None. This spec ships no endpoints. (Explicitly stating this per the plan template — not an
oversight.)

## Retrieval / ingestion impact

None. Qdrant is untouched; `packages/ingestion`/`packages/retrieval` are untouched. Explicitly
out of scope per spec.md Non-goals.

## Security / tenancy impact

Yes — this is where RLS policies are first defined, even though nothing enforces the
`app.current_tenant_id` session variable yet. Concretely:

- **What's real after this spec:** the schema fails closed — any session that queries a
  tenant-scoped table without setting the GUC gets zero rows, not all rows. There is no way
  to accidentally ship a caller that "forgets" isolation and gets full access by default.
- **What's still missing:** nothing sets the GUC yet (that's `011`), and there's no
  authorization test suite yet proving cross-tenant queries are blocked in a live request path
  (also `011`, since there's no request path). This spec's own tests only prove the policy
  exists and behaves correctly for a manually-set GUC in a test session — not an end-to-end
  authorization guarantee.
- Object storage: keys are namespaced `{tenant_id}/{workspace_id}/{document_id}/...`
  (see below), but the MinIO/S3 client itself enforces no access control at this layer — that
  namespacing is for organization and future bucket-policy scoping, not a security boundary by
  itself. The security boundary is "only `packages/storage` callers with a legitimate
  `tenant_id`/`workspace_id` construct these keys," which holds once `011`'s auth layer is the
  only thing constructing them from resolved identity (never from client input, matching
  `06-security-model.md` §4).

## Storage key scheme

- Raw PDFs: `{tenant_id}/{workspace_id}/{document_id}/{content_hash}.pdf`
- Extracted images (written by a later ingestion spec, but the scheme is fixed now so
  `document_versions.object_storage_key`-style references are stable):
  `{tenant_id}/{workspace_id}/{document_id}/{document_version_id}/images/{image_index}.png`
- Single shared bucket (`mm-rag-documents` locally), prefix-partitioned — not bucket-per-tenant
  — consistent with the Qdrant payload-partitioning strategy already chosen in
  `02-data-model.md` §3 (assignment 3.4's explicit guidance against per-tenant collections
  applies the same way to buckets).
- Idempotency: `upload()` checks `exists(key)` first; if the key already exists, it's a no-op
  (same content_hash implies same bytes) rather than re-uploading. A race between two
  concurrent uploads of identical content is harmless — both would write identical bytes to
  the same key.
- The storage client is written against boto3's generic S3 API (`endpoint_url` is
  configurable), so this is a config change, not a code change, when moving from MinIO to real
  AWS S3.

## Session/engine strategy

`packages/db` exposes both:
- A **sync** engine/session factory (`psycopg` v3 driver) — used by Alembic (autogenerate and
  migration execution require sync) and by anything running in a Celery worker context later
  (`020-async-ingestion-pipeline`), since Celery tasks are sync by default.
- An **async** engine/session factory (`asyncpg` driver) — used by `apps/api` once it exists
  (`011`), since FastAPI routes are async.

Both point at the same Postgres instance/schema via the same SQLAlchemy declarative models;
only the engine/session layer differs. `DATABASE_URL` is derived from `POSTGRES_USER` /
`POSTGRES_PASSWORD` / `POSTGRES_DB` (already in `infra/.env.example`) plus new `POSTGRES_HOST`
(default `localhost` for local dev) and `POSTGRES_PORT` (default `5432`) entries, with the
driver (`+psycopg` vs `+asyncpg`) selected by which factory is called.

## New dependencies (first `pyproject.toml` for this repo)

No `pyproject.toml`/`uv.lock` exists yet anywhere in the repo — this spec creates the first
one, scoped to what it needs: `sqlalchemy`, `alembic`, `psycopg[binary]`, `asyncpg`, `boto3`,
`pydantic-settings`, plus `pytest`/`pytest-asyncio` as dev dependencies. Nothing
generation/retrieval/parsing-related is added here — those land with the specs that need them.

## Config additions

`infra/.env.example` gets new entries: `POSTGRES_HOST=localhost`, `POSTGRES_PORT=5432`,
`S3_ENDPOINT_URL=http://localhost:9000`, `S3_BUCKET=mm-rag-documents`. For local dev, the app's
S3 credentials reuse `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD` (already present) rather than
provisioning a separate scoped IAM-style user — a scoped-credential setup is real production
hardening but not justified for a single local-dev MinIO instance with no other tenants of the
bucket; flagged here so it isn't forgotten before a real deployment.

## Rollout

No feature flag — nothing user-facing exists to gate. Rollout is "run
`alembic upgrade head` against each environment's Postgres as it's stood up." Revert is
`alembic downgrade` one step, which drops the RLS policies and tables cleanly since there's no
production data yet.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| RLS policy written against the wrong GUC name/type once `011` starts setting it, silently failing closed (zero rows) or open (all rows) | Medium | High — is the exact bug class this schema exists to prevent | This spec's tests assert both: GUC unset -> zero rows, GUC set to a real `tenant_id` -> only matching rows. `011`'s plan must reference this exact GUC name (`app.current_tenant_id`) rather than reinventing it |
| Pooled connection reuse causes a stale/empty GUC value to raise a cast error instead of denying cleanly | Low (mitigated in this spec) | Medium (an error is still fail-closed from a data-exposure standpoint, but is an availability/noise problem) | Fixed via `NULLIF(current_setting(...), '')` in the policy expression, verified by `tests/integration/test_rls.py` against a real Postgres; `011`'s connection-pool design should still document that every request must set (not just conditionally set) the GUC |
| Denormalized `tenant_id` drifts from the parent row's `tenant_id` if application code ever updates a `workspace_id` FK without updating the copy | Low (no update path exists yet — rows are created once, not re-parented) | High if it happens | Documented here and in the updated `02-data-model.md`; a future spec that adds any "move workspace" style mutation must update both columns in the same transaction |
| Sync+async dual engine setup is more moving parts than a single engine | Medium | Low | Standard, well-documented SQLAlchemy 2.0 pattern; only `packages/db` internals are aware of it — callers just get a session |
| MinIO vs real AWS S3 API parity gaps surface later (e.g. some S3 features MinIO doesn't implement) | Low for basic put/get/delete/exists, which is all this spec uses | Medium | Generic `boto3` interface means the fix is a config/endpoint change, not a rewrite, if a gap is found |

## Alternatives considered

- **RLS via subqueries on the existing join path (no denormalized `tenant_id`)** — rejected:
  correct but means every policy is a multi-table subquery instead of an indexed equality
  check, on every single row-read, forever. The denormalized column costs one extra indexed
  column per table and one insert-time assignment; worth it for a check that runs on every
  query for the life of the system.
- **Single engine (sync-only) for everything, async added later** — rejected: `011` will need
  async for FastAPI and `020` will need sync for Celery; building both now against the same
  models is cheaper than retrofitting async support after `apps/api` already has a shape.
- **Bucket-per-tenant** — rejected for the same reason `02-data-model.md` already rejected
  collection-per-tenant in Qdrant: operationally heavier (bucket provisioning per signup) for
  no isolation benefit once prefix-based access patterns and, later, bucket policies exist.
