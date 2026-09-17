# Data Model — Multi-Tenant, Versioned, Permissioned

- **Status:** approved baseline
- **Stores:** PostgreSQL (system of record) + Qdrant (vector/payload projection)

> ⚠️ **Single-tenant as-built — see [`specs/012-single-tenant-simplification`](../012-single-tenant-simplification/spec.md).**
> `012` removed the tenant layer for assignment scope: no `tenants` / `tenant_members` /
> `usage_quotas` tables, no `tenant_id` column on any table. `api_keys` and `audit_log` are
> workspace-scoped. See §0 below for the live schema, including the workspace-scoped
> Row-Level Security `specs/030-workspace-rbac-filtering` added as defense-in-depth. The
> multi-tenant design in §1–§4 is retained as the deferred target (roadmap Phase 10);
> parts that are not currently implemented are marked ⚠️ DEFERRED.

## 0. As-built schema (single-tenant)

Live entities after `012`. Isolation is per-workspace, enforced at the application layer
(every query filters by `workspace_id` behind a `workspace_members` role check) plus
workspace-scoped Postgres Row-Level Security as defense-in-depth (migration `0002`,
`specs/030-workspace-rbac-filtering`; migration `0003`, `specs/051-table-intelligence`) on
`documents`, `document_versions`, `ingestion_jobs`, `api_keys`, `audit_log`,
`document_tables`, `table_cells` — keyed on an `app.current_workspace_id` session GUC, with
`FORCE ROW LEVEL SECURITY` since the app's single DB user owns every table. Everything
except `documents`/`api_keys`/`audit_log` has no direct `workspace_id` column (below), so
their policy joins to `documents` rather than a denormalized column. `workspaces`/
`workspace_members` are deliberately not RLS-protected (the caller's role must be
resolvable from `workspace_members` before the GUC can exist); `conversations`/`messages`/
`message_feedback` aren't yet either (no route reads or writes them).

```
users                 id, email (unique), display_name,
                      auth_provider_subject (unique), created_at
workspaces            id, name, created_by (fk users), created_at
workspace_members     workspace_id + user_id (pk), role owner|editor|viewer
documents             id, workspace_id (fk), filename, content_hash_current,
                      status, current_version_id (fk document_versions, nullable),
                      created_by, created_at, updated_at
document_versions     id, document_id (fk), version_number, content_hash,
                      object_storage_key, page_count, is_current, superseded_at, created_at
ingestion_jobs        id, document_id (fk), document_version_id (fk), status,
                      failure_stage, failure_reason, retry_count,
                      started_at, finished_at, created_at
conversations         id, workspace_id (fk), created_by, title, is_shared,
                      share_token (nullable unique), created_at
messages              id, conversation_id (fk), role user|assistant, content,
                      sources_json, used_images_json, model_name, usage_json,
                      latency_ms, created_at
message_feedback      id, message_id (fk), user_id (fk), rating up|down, comment, created_at
api_keys              id, workspace_id (fk), key_hash (unique), scopes,
                      created_by, revoked_at, created_at
audit_log             id, workspace_id (fk, nullable), actor_user_id (nullable),
                      action, resource_type, resource_id, metadata_json, created_at
document_tables       id, document_id (fk), document_version_id (fk), table_index,
                      page_number, object_storage_key, summary, schema_json, row_count,
                      created_at
table_cells           id, table_id (fk document_tables), document_id (fk), row_index,
                      column_name, value, created_at
```

Indexes: `workspace_members(user_id)`, `documents(workspace_id)`,
`document_versions(document_id, version_number)`, `ingestion_jobs(status)`,
`conversations(workspace_id)`, `api_keys(workspace_id)`,
`audit_log(workspace_id, created_at)`, `document_tables(document_id)`,
`document_tables(document_version_id)`, `table_cells(document_id)`,
`table_cells(table_id)`; `table_cells` also has a unique constraint on
`(table_id, row_index, column_name)`. Object-storage keys are
`{workspace_id}/{document_id}/…`. Qdrant point payload carries `workspace_id` (no
`tenant_id`); required payload indexes drop `tenant_id`.

---

_The remainder of this document describes the deferred multi-tenant target._

## 1. Why two stores

PostgreSQL owns identity, ownership, membership, permissions, job state, conversations, and
audit — anything relational that needs joins, transactions, or exact-match integrity. Qdrant
owns vectors and a **denormalized copy** of the subset of metadata needed to filter search
results (`tenant_id`, `workspace_id`, `document_id`, `document_version_id`, `content_type`,
`visibility`). Qdrant is never the source of truth for who-can-see-what — it just needs to be
fast to filter on. If Postgres and Qdrant ever disagree, Postgres wins and Qdrant is
re-synced (this is what the versioning/incremental-ingestion job in `03-ingestion-workflow.md`
does).

## 2. PostgreSQL schema (entities)

```
tenants
  id (uuid, pk)
  name
  slug (unique)
  plan_tier                 -- free/pro/enterprise, drives usage_quotas
  created_at

users
  id (uuid, pk)
  email (unique)
  display_name
  auth_provider_subject     -- unique; sub claim from IdP (Keycloak, self-hosted per
                             -- 06-security-model.md §2 / 011-auth-and-workspaces)
  created_at

tenant_members
  tenant_id (fk tenants)
  user_id (fk users)
  role                      -- 'owner' | 'admin' | 'member'
  PRIMARY KEY (tenant_id, user_id)

workspaces
  id (uuid, pk)
  tenant_id (fk tenants)
  name
  created_by (fk users)
  created_at

workspace_members
  workspace_id (fk workspaces)
  user_id (fk users)
  tenant_id (fk tenants)     -- denormalized from workspaces.tenant_id, see note below
  role                      -- 'owner' | 'editor' | 'viewer'
  PRIMARY KEY (workspace_id, user_id)

documents
  id (uuid, pk)
  workspace_id (fk workspaces)
  tenant_id (fk tenants)     -- denormalized from workspaces.tenant_id, see note below
  filename
  content_hash_current      -- sha256 of the latest uploaded bytes
  status                    -- see 03-ingestion-workflow.md state machine
  current_version_id (fk document_versions, nullable until first version is ready)
  created_by (fk users)
  created_at
  updated_at

document_versions
  id (uuid, pk)
  document_id (fk documents)
  tenant_id (fk tenants)     -- denormalized from documents.tenant_id, see note below
  version_number             -- monotonic per document, starts at 1
  content_hash                -- sha256 of the bytes this version was built from
  object_storage_key          -- where the raw PDF lives
  page_count
  is_current (bool)
  superseded_at (nullable)
  created_at

ingestion_jobs
  id (uuid, pk)
  document_id (fk documents)
  document_version_id (fk document_versions)
  tenant_id (fk tenants)     -- denormalized from documents.tenant_id, see note below
  status                     -- queued|parsing|chunking|embedding|indexing|ready|failed
  failure_stage (nullable)
  failure_reason (nullable)
  retry_count (int, default 0)
  started_at / finished_at
  created_at

conversations
  id (uuid, pk)
  workspace_id (fk workspaces)
  tenant_id (fk tenants)     -- denormalized from workspaces.tenant_id, see note below
  created_by (fk users)
  title
  is_shared (bool)
  share_token (nullable, unique)
  created_at

messages
  id (uuid, pk)
  conversation_id (fk conversations)
  tenant_id (fk tenants)     -- denormalized from conversations.tenant_id, see note below
  role                        -- 'user' | 'assistant'
  content
  sources_json                -- citation list returned with this message
  used_images_json
  model_name
  usage_json                  -- tokens/cost, see 07-evaluation-observability.md
  latency_ms
  created_at

message_feedback
  id (uuid, pk)
  message_id (fk messages)
  tenant_id (fk tenants)     -- denormalized from messages.tenant_id, see note below
  user_id (fk users)
  rating                      -- 'up' | 'down'
  comment (nullable)
  created_at

api_keys
  id (uuid, pk)
  tenant_id (fk tenants)
  key_hash                    -- never store raw key
  scopes                      -- e.g. ['documents:read','chat:write']
  created_by (fk users)
  revoked_at (nullable)
  created_at

audit_log
  id (uuid, pk)
  tenant_id (fk tenants)
  actor_user_id (fk users, nullable for system actions)
  action                       -- 'document.upload' | 'document.delete' | 'chat.query' | ...
  resource_type / resource_id
  metadata_json
  created_at

usage_quotas
  tenant_id (fk tenants, pk)
  period_start / period_end
  documents_ingested_count
  storage_bytes_used
  queries_count
  tokens_used
  quota_documents / quota_storage_bytes / quota_queries / quota_tokens
```

Indexes: `documents(workspace_id)`, `document_versions(document_id, version_number)`,
`ingestion_jobs(status)` (worker polling / dashboards), `workspace_members(user_id)` (fast
"which workspaces can this user see" lookup used to build the retrieval filter),
`audit_log(tenant_id, created_at)`. Every denormalized `tenant_id` column below is also
indexed.

Denormalized `tenant_id`: `documents`, `document_versions`, `ingestion_jobs`, `conversations`,
`messages`, and `message_feedback` carry a direct `tenant_id` column in addition to reaching
it transitively via `workspace_id`/`document_id`/`conversation_id` joins (per
`specs/010-metadata-db-and-object-storage/plan.md`). This keeps every Row-Level Security
policy a single indexed equality check instead of a multi-level subquery on every row access.
The column is populated at insert time from the parent's `tenant_id` and is never
independently settable — any future mutation that re-parents a row (e.g. moving a document to
a different workspace) must update both columns in the same transaction.

`workspace_members` also carries a denormalized `tenant_id`, added later by
`specs/011-auth-and-workspaces/plan.md` for a different reason than the tables above: it's not
about avoiding a join at query time, it's about **bootstrap ordering**. `workspace_members`
(like `tenant_members`) deliberately carries no Row-Level Security, so it can be queried to
resolve a caller's role *before* `app.current_tenant_id` is known. Without `tenant_id` sitting
right there, resolving which tenant a `workspace_id` belongs to would require querying
`workspaces` — which *is* RLS-protected, and would return nothing before the GUC is set.
Carrying `tenant_id` on `workspace_members` lets one pre-GUC query answer both "does this
caller have workspace access" and "which tenant do I scope the GUC to."

Row-level isolation: every tenant-scoped table carries `tenant_id` (directly or via
`workspace_id -> workspaces.tenant_id`), and Postgres Row-Level Security policies key off
`current_setting('app.current_tenant_id')`, set per-request by the API layer as
defense-in-depth behind the application-level filtering described in `06-security-model.md`.

## 3. Qdrant payload schema

One collection per embedding-dimension/model family (e.g. `mm_rag_v1`), **not** one
collection per tenant — payload-based partitioning as the assignment requires (3.4). Every
point (chunk) payload:

```json
{
  "tenant_id": "uuid",
  "workspace_id": "uuid",
  "document_id": "uuid",
  "document_version_id": "uuid",
  "is_current_version": true,
  "content_type": "page_text_plus_ocr | table | image",
  "page_number": 12,
  "chunk_index": 3,
  "table_index": null,
  "image_index": null,
  "image_path": "s3://.../page_012_image_1.png",
  "filename": "Client_Contracts.pdf",
  "visibility": "workspace",
  "text": "the chunk's source text, as embedded",
  "created_at": "2026-08-17T..."
}
```

This is a direct extension of the existing metadata already produced by
`src/ingestion.py::prepare_documents` (`document_id`, `filename`, `content_type`,
`page_number`, `chunk_index`, `table_index`, `image_index`, `image_path`) — we are adding
`tenant_id`, `workspace_id`, `document_version_id`, `is_current_version`, and `visibility`.
`text` was added later, by `specs/030-workspace-rbac-filtering` — the chunk was always
embedded from it, but nothing stored it until that phase's search endpoint needed something
to return besides a score and metadata. The as-built (single-tenant) payload matches this
minus `tenant_id` (§0).

Since `specs/040-hybrid-retrieval-reranking`, every point also carries a **named `"sparse"`
vector** (BM25, via `fastembed.SparseTextEmbedding`) alongside the unnamed default dense
vector shown above — same point, same payload, two vectors. This required recreating the
Qdrant collection (`packages/ingestion/qdrant_setup.py::ensure_collection`): Qdrant does not
support adding a new named vector to an existing collection in place, only creating it or
updating an already-configured one's index settings.

Required payload indexes (extending the existing `_ensure_collection` index set in
`src/ingestion.py`): `tenant_id`, `workspace_id`, `document_id`, `document_version_id`,
`is_current_version`, `content_type`, `page_number` (already present today as
`metadata.document_id`, `metadata.filename`, `metadata.file_sha256`, `metadata.content_type`,
`metadata.page_number` — note the field path changes from `metadata.*` to top-level once
points are written by the new ingestion service; the migration plan for existing data lives
in the spec that implements this phase, not here).

## 4. Entity relationship summary

```
tenants 1---N workspaces 1---N documents 1---N document_versions 1---N ingestion_jobs
tenants 1---N tenant_members N---1 users
workspaces 1---N workspace_members N---1 users
workspaces 1---N conversations 1---N messages 1---N message_feedback
document_versions --(fan-out at ingest time)--> Qdrant points (tenant_id/workspace_id/
  document_id/document_version_id in payload)
```

## 5. Related docs

- `03-ingestion-workflow.md` — how `documents` / `document_versions` / `ingestion_jobs` rows
  move through states
- `06-security-model.md` — how `workspace_members` role drives the mandatory retrieval filter
- `09-repo-and-module-structure.md` — where SQLAlchemy models / Alembic migrations live
