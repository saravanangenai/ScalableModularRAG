# Spec: Metadata DB and Object Storage

- **ID:** `010-metadata-db-and-object-storage`
- **Roadmap phase:** [08-roadmap.md](../architecture/08-roadmap.md) Phase 2 — Metadata DB + Object Storage + Auth + Multi-Doc (this spec covers the DB/storage half; auth and workspace membership are `011-auth-and-workspaces`)
- **Status:** approved
- **Owner:** Saravanan Shanmugam
- **Date:** 2026-08-22

## Problem statement

Today there is no metadata database and no durable object storage — the V1 prototype
(`src/*`) reads/writes local disk under `data/` and holds no record of documents, versions,
users, tenants, or jobs anywhere. Every downstream phase in the roadmap (auth, tenant
isolation, async ingestion, quotas, audit) needs a real relational store for identity,
ownership, and job state, and durable storage for the raw PDFs and extracted images that
currently only exist as local files. Per [08-roadmap.md](../architecture/08-roadmap.md), this
is deliberately pulled forward ahead of retrieval/quality work because nothing else can be
built safely on top of local files.

## Goals

- Every entity in [02-data-model.md](../architecture/02-data-model.md) §2 exists as a durable
  PostgreSQL table, reachable through versioned migrations (schema can be built from scratch
  or upgraded incrementally).
- Raw PDFs and extracted images can be written to and read back from object storage
  (S3-compatible — MinIO locally, per `infra/docker-compose.yml`), addressed so a
  `document_versions.object_storage_key` reliably round-trips to the same bytes.
- Row-level tenant isolation is defined at the schema level (Postgres RLS policies exist on
  every tenant-scoped table), even though nothing enforces the session variable yet — that
  wiring is `011-auth-and-workspaces`.
- The schema and storage client are usable as a library from any future caller
  (`apps/api`, Celery workers, `eval/`) without any of them existing yet — this spec ships no
  API endpoints and no UI.
- `packages/db` and `packages/storage` wrap and re-raise underlying driver/SDK errors as
  typed exceptions (`packages/exceptions`) at their public function boundaries, carrying
  enough context (operation, table/key) to be actionable — but do not log. Logging on failure
  is the responsibility of the calling service layer (API routes, ingestion orchestration),
  which has the request/job context to log meaningfully; that caller doesn't exist yet and is
  out of scope here (see Non-goals).

## Non-goals

- No authentication, no JWT verification, no IdP integration — that's
  `011-auth-and-workspaces`.
- No API routes in `apps/api` — nothing here is reachable over HTTP yet. This spec only
  produces importable `packages/db` and `packages/storage` code plus migrations.
- No Celery/Redis job queue or parser worker wiring — that's `020-async-ingestion-pipeline`.
  `ingestion_jobs` rows are modeled here (schema only) but nothing writes to them yet.
- No Qdrant collection or payload changes — those are exercised when ingestion/retrieval
  phases actually write vectors; this spec is Postgres + object storage only.
- No data migration from the V1 prototype's local `data/` files — out of scope until a
  concrete migration need exists (there is no production data to migrate yet).
- No production secrets-manager integration ([06-security-model.md](../architecture/06-security-model.md)
  §6) — local dev only, credentials via `infra/.env` as already scaffolded.

## User-facing behavior

None yet — this is infrastructure with no UI or API surface. The observable behavior is at
the developer/CI level:

- A developer can run a migration command against a fresh Postgres (the
  `infra/docker-compose.yml` `postgres` service) and get every table in
  [02-data-model.md](../architecture/02-data-model.md) §2, with the documented foreign keys
  and indexes.
- Code importing `packages/db` can open a session and perform CRUD against any of those
  tables via ORM models.
- Code importing `packages/storage` can upload a file, get back a key, and retrieve the exact
  same bytes using that key, against the `infra/docker-compose.yml` `minio` service.

## Acceptance criteria

- [ ] Running the migration tool against a clean Postgres database creates all tables listed
      in [02-data-model.md](../architecture/02-data-model.md) §2 (`tenants`, `users`,
      `tenant_members`, `workspaces`, `workspace_members`, `documents`, `document_versions`,
      `ingestion_jobs`, `conversations`, `messages`, `message_feedback`, `api_keys`,
      `audit_log`, `usage_quotas`), with the foreign keys and indexes documented there.
- [ ] Every table has a corresponding ORM model importable from `packages/db`.
- [ ] A round-trip integration test creates a `tenant` -> `workspace` -> `document` ->
      `document_version` chain via the ORM and reads each row back unchanged.
- [ ] Row-Level Security policies exist (via migration) on every table that carries or
      inherits `tenant_id`, keyed off a session-scoped setting — even though no caller sets
      that setting yet (that lands in `011`).
- [ ] `packages/storage` exposes upload/download/delete operations against an S3-compatible
      backend; an integration test uploads a file to the local MinIO container, downloads it,
      and confirms byte-for-byte equality, then deletes it and confirms it's gone.
- [ ] Object storage keys are content-hash-addressed so that re-uploading identical bytes for
      a new `document_versions` row is either idempotent or produces a deterministic
      collision result (exact behavior decided in `plan.md`).
- [ ] Migrations are reversible (a downgrade path exists) or the plan explicitly justifies why
      not, per standard Alembic practice.
- [ ] No changes to `apps/*` or `packages/ingestion`/`packages/retrieval`/`packages/generation`.
- [ ] `packages/db` and `packages/storage` never call `structlog`/any logger directly — a test
      or code-review check confirms failures propagate as typed exceptions from
      `packages/exceptions` instead of being logged and swallowed at the source.
- [ ] `tests/unit` and/or `tests/integration` cover the above; tests run against the
      `infra/docker-compose.yml` services, not mocks, for the storage/DB round-trip checks
      (per this project's stated preference for testing against real dependencies over
      mocking the database).

## Constraints

- Must match the schema in [02-data-model.md](../architecture/02-data-model.md) exactly
  (column names, types implied there, relationships) — if implementation reveals the doc is
  wrong or incomplete, update the doc in the same session rather than silently diverging.
- Must run against the `postgres` and `minio` services already defined in
  `infra/docker-compose.yml` — no new infra containers introduced by this spec.
- Python 3.12, `uv`-managed, per `CLAUDE.md` conventions. Exceptions from this package must
  follow the `DocumentPortalException`-style wrapping convention once `packages/exceptions`
  exists (may be a small addition in this spec if nothing is there yet).
- No provider API keys (OpenAI, Qdrant) touched by this spec at all — it's pure DB/storage.

## Open questions

None — resolved. The storage abstraction is written against a generic S3-compatible
interface (`boto3`, pointed at MinIO locally via `infra/.env`), so swapping to real AWS S3
later is a config/endpoint change only, not a code change.
