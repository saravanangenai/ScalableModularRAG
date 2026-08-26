# Plan: Async Ingestion Pipeline

- **Spec:** [spec.md](spec.md) (approved 2026-08-24)
- **Status:** approved (2026-08-24)

## Summary

Port the V1 prototype's `ComplexPDFParser` (`src/parsing.py`) and
`MultimodalDocumentIngestion` (`src/ingestion.py`) into `packages/parsing`/`packages/ingestion`
unchanged in parsing behavior, running behind a Celery/Redis-protocol job queue instead of the
Streamlit request thread. `apps/api` gains `documents` and `jobs` routers (upload, list, detail,
version history, job status), reusing `011`'s `require_workspace_role` auth as-is. A new
`workers/celery_app.py` process executes one ingestion job per document version, writing
`ingestion_jobs.status` transitions to Postgres and chunks to a new Qdrant collection with the
full tenant-scoped payload from `02-data-model.md` §3.

## Architecture doc deltas

| Doc | Change |
|---|---|
| `09-repo-and-module-structure.md` §4 | The `documents`/`jobs` router table shows bare `GET /documents/{id}`, `GET /documents/{id}/versions`, `GET /jobs/{id}`. Changed to nest all of them under `/workspaces/{workspace_id}/...` — see "API contract" below for why this isn't optional. |
| `03-ingestion-workflow.md` §3 | The "parsing" stage description currently says "...and (new, see `05-multimodal-strategy.md`) vision captioning of images" — this spec does **not** do vision captioning (see spec.md Non-goals; `08-roadmap.md` places it in Phase 6). Wording corrected to describe OCR-only image handling, with a forward-pointer to Phase 6 for captioning. |
| `CLAUDE.md` | States structured logging lives in `packages/observability/` "once built." This spec builds a minimal version of it (see Component/module ownership) — first package in this repo that actually needs operational log visibility (a long-running background worker, not a short request/response call). |

## Component/module ownership

- **`packages/parsing`** (new) — `pdf_parser.py`: `ComplexPDFParser`, ported near-verbatim
  from `src/parsing.py`. Same public API (`parse(save_output=...) -> {pages, images, tables,
  documents, output_dir}`), same libraries (PyMuPDF, pdfplumber, pytesseract). Exceptions
  wrapped as `ParsingError` (`packages/exceptions`) instead of the prototype's
  `DocumentPortalException` import; no direct logging (see `packages/observability` below —
  matches the calling convention, not the prototype's, since the prototype logs at every
  step but this repo's established convention has library packages stay silent and let the
  caller log with request/job context).
- **`packages/ingestion`** (new)
  - `pipeline.py` — orchestrates one document version end-to-end: read PDF bytes from
    `packages/storage`, call `packages/parsing`, chunk (ported from
    `MultimodalDocumentIngestion.prepare_documents`/`_split`), embed (dense only, via
    `langchain-openai`, matching V1), upsert into Qdrant with the extended payload, update
    `ingestion_jobs.status` at each stage transition. Raises `IngestionError` on failure.
  - `versioning.py` — `content_hash` computation (sha256, matching `010`'s storage-key
    scheme and V1's `file_fingerprint`), "does this hash match the document's current
    version" check, new-version creation.
  - `qdrant.py` — collection/payload-index setup (`_ensure_collection` equivalent, extended
    with the payload indexes from `02-data-model.md` §3: `tenant_id`, `workspace_id`,
    `document_id`, `document_version_id`, `is_current_version`, `content_type`,
    `page_number`).
- **`workers/celery_app.py`** (new) — Celery app + one task, `run_ingestion_job(job_id: str,
  tenant_id: str)`, imported by nothing except itself (invoked via `celery -A
  workers.celery_app worker`). **`tenant_id` is passed explicitly as a task argument by the
  enqueuer, not looked up by the worker** — `ingestion_jobs` is itself RLS-protected
  (`TENANT_SCOPED_TABLES`), so a worker-side query for "what tenant does job X belong to"
  would be blocked by the very policy it's trying to unlock (this plan originally said the
  worker would "read the job's own `tenant_id` column... before any other tenant-scoped
  query" — that's not actually possible under RLS and was caught before writing code, not
  after; see "Implementation findings" below). The API route that enqueues the job already
  knows `tenant_id` from its own authenticated `require_workspace_role` context, so it's
  passed straight through as a Celery task argument. The worker calls
  `packages.auth.context.set_tenant_scope(session, tenant_id)` using that argument before
  touching any `TENANT_SCOPED_TABLES` row, including `ingestion_jobs` itself.
- **`packages/observability`** (new, minimal) — `logging.py`: one `structlog` configuration
  function (`configure_logging()`), called once at worker/API startup. `snake_case_event_name`
  + keyword fields, per `CLAUDE.md`. Only `packages/parsing`'s caller (`packages/ingestion`)
  and `workers/celery_app.py` use it directly — `packages/db`/`storage`/`auth` stay silent,
  unchanged from `010`/`011`.
- **`apps/api/routers/documents.py`** (new) — `POST /workspaces/{id}/documents`,
  `GET /workspaces/{id}/documents`, `GET /workspaces/{id}/documents/{document_id}`,
  `GET /workspaces/{id}/documents/{document_id}/versions`.
- **`apps/api/routers/jobs.py`** (new) — `GET /workspaces/{id}/jobs/{job_id}`.
- **`packages/exceptions`** — add `parsing.py` (`ParsingError`), `ingestion.py`
  (`IngestionError`), both `DocumentPortalException` subclasses.
- **`packages/auth/context.py`** gets one small addition: `set_tenant_scope_sync`, a sync
  counterpart of the existing async `set_tenant_scope` — `011` only built the async path
  (for `apps/api`); the Celery worker needs the same GUC-setting logic against a sync
  session (Celery tasks are sync by default, per `010`'s "Session/engine strategy"). Same
  one-line body, just non-async. No other changes to `packages/db`/`packages/auth`/
  `apps/api/deps` beyond reuse — `010`'s schema and `011`'s `require_workspace_role` are used
  exactly as they exist.

## Data model changes

**None in Postgres** — `documents`, `document_versions`, `ingestion_jobs` already have every
column this spec needs, from `010`. This spec is their first writer.

**New Qdrant collection** (`mm_rag_v1`, per `02-data-model.md` §3's naming), created on
worker/API startup if missing, with payload indexes on `tenant_id`, `workspace_id`,
`document_id`, `document_version_id`, `is_current_version`, `content_type`, `page_number` —
already specified in `02-data-model.md`, implemented here for the first time.

## API contract

All routes below require a verified JWT or API key (per `011`), resolved via
`require_workspace_role` exactly as built — **every route is nested under
`/workspaces/{workspace_id}/...`**, including document-detail and job-status routes that
`09-repo-and-module-structure.md`'s indicative table showed as bare `/documents/{id}` and
`/jobs/{id}`.

**Why this isn't optional, not just a style choice:** `documents` and `ingestion_jobs` are
both `TENANT_SCOPED_TABLES` (RLS-protected, `FORCE ROW LEVEL SECURITY`, from `010`). A bare
`GET /documents/{document_id}` route would need to resolve that document's `workspace_id`
*before* the RLS GUC can be set — but looking that up means querying the `documents` table
itself, which is exactly the RLS-protected table that query can't see anything in yet. This
is the identical bootstrap-ordering trap `011` hit twice (`api_keys`, then
`workspace_members`) — caught here during planning instead of during implementation/testing,
by applying the lesson directly: every route's role-check dependency must receive its
tenant/workspace scope from an unprotected source (the URL path, resolved via
`workspace_members`), never from a query against a protected table.

| Method & path | Auth | Body | Success | Errors |
|---|---|---|---|---|
| `POST /workspaces/{workspace_id}/documents` | workspace `editor`+ | `multipart/form-data`: `file` (PDF) | `202 {document_id, document_version_id, job_id, status: "queued"}`; or `200 {document_id, document_version_id, status: "unchanged"}` if `content_hash` matches the current version | `401`/`403`/`404`, `415` (not a PDF), `413` (too large) |
| `GET /workspaces/{workspace_id}/documents` | workspace `viewer`+ | — | `200 [DocumentOut]` | `401`/`403`/`404` |
| `GET /workspaces/{workspace_id}/documents/{document_id}` | workspace `viewer`+ | — | `200 DocumentOut` | `401`/`403`/`404` |
| `GET /workspaces/{workspace_id}/documents/{document_id}/versions` | workspace `viewer`+ | — | `200 [DocumentVersionOut]` | `401`/`403`/`404` |
| `GET /workspaces/{workspace_id}/jobs/{job_id}` | workspace `viewer`+ | — | `200 JobOut {status, failure_stage, failure_reason, retry_count, started_at, finished_at}` | `401`/`403`/`404` |

`DELETE /documents/{id}` and `GET /jobs/{id}/events` (SSE) from `09`'s indicative table are
explicitly out of scope here per spec.md Non-goals — not forgotten, deliberately deferred.

**Document identity across uploads** (not previously specified — resolved here): the upload
endpoint has no `document_id` in its path, so it must decide itself whether an upload is a
new document or a new version of an existing one. Matching V1's behavior (identity derived
from the file path/name), this is resolved as: **same `filename` within the same
`workspace_id`** -> treated as the same document (version-diff via `content_hash` per
`03-ingestion-workflow.md` §5); any other filename -> a brand-new `documents` row
(`version_number` starts at 1). This is a workspace-scoped, case-sensitive exact match — no
fuzzy matching, no cross-workspace matching.

## Retrieval / ingestion impact

This spec **is** the ingestion pipeline. No `packages/retrieval` code exists yet or is
touched. Qdrant points get written with `is_current_version`/`tenant_id`/`workspace_id` in
the payload so Phase 4 (`030-039`) has real data to filter on, but no query path exists yet
to exercise that filtering.

## Security / tenancy impact

- Every new API route is authenticated/scoped through `011`'s existing
  `require_workspace_role` — no new auth mechanism, no route bypasses it.
- The Celery worker is a trusted background process, not a public endpoint. It never accepts
  external input for `tenant_id` — it reads its own job's `tenant_id` column (written by an
  already-authenticated API request at enqueue time) and sets the RLS GUC from that before
  touching any other tenant-scoped table. This mirrors exactly how `011`'s
  `require_tenant_role` handles the API-key bootstrap case: read a value from a trusted
  source, only then set the GUC.
- Object storage keys are constructed exactly per `010`'s scheme
  (`{tenant_id}/{workspace_id}/{document_id}/{content_hash}.pdf`,
  `.../{document_version_id}/images/{image_index}.png`) — nothing new invented.

## Rollout

No feature flag. `documents`/`document_versions`/`ingestion_jobs` exist but have zero rows
today — this is purely additive, nothing regresses. Revert is "don't start the worker /
don't register the new routers" — `011`'s routes are untouched.

## Implementation findings

- **A third instance of the RLS bootstrap-ordering trap, caught while writing
  `packages/ingestion/pipeline.py`.** This plan originally described the Celery worker
  "reading the job's own `tenant_id` column... before any other tenant-scoped query" to
  decide what to set the RLS GUC to. That's impossible: `ingestion_jobs` is
  RLS-protected, so a query for that row — even just its `tenant_id` column — is blocked
  by the same policy the GUC is supposed to unlock, for exactly the same reason `011` hit
  this twice (`api_keys`, `workspace_members`) and this plan's API-contract section hit it
  a second time for document/job detail routes. Fixed by having the enqueuer (the
  authenticated API route, which already has `tenant_id` from `require_workspace_role`)
  pass it as an explicit Celery task argument — see Component/module ownership above. This
  makes four total occurrences of this exact bug class across `011` and `020`; worth
  treating as a standing design rule for any future spec: **never make an RLS-protected
  table the source of the value needed to set the RLS GUC in the first place** — that value
  must come from an unprotected table, a path/argument the caller already trusted, or be
  passed explicitly by whoever already has it.
- **`langchain-qdrant` dropped in favor of using `qdrant-client` directly.** V1 writes
  points via `QdrantVectorStore.add_documents()`, which nests all metadata under a
  `metadata.*` payload path (e.g. `metadata.document_id`) — that's exactly what
  `02-data-model.md` §3 explicitly calls out as the *old* shape: "note the field path
  changes from `metadata.*` to top-level once points are written by the new ingestion
  service." Using `langchain-qdrant`'s default integration would have silently reproduced
  the old nested shape instead of the flat one this spec is supposed to produce. Writing
  points directly via `qdrant_client.QdrantClient.upsert()` with explicit
  `models.PointStruct(payload={...})` gives full control over the flat shape and removes an
  unneeded dependency (`langchain-openai`/`langchain-core`/`langchain-text-splitters` are
  still used, just not `langchain-qdrant`).
- **`documents.content_hash_current` alone isn't a safe "unchanged" signal.** The upload
  route has to set it at creation time (the column is `NOT NULL`), before the first
  ingestion job for a document has even run. If that first job then fails, a later
  byte-identical re-upload would compare its hash against `content_hash_current`, match, and
  short-circuit as `"unchanged"` — silently refusing to ever retry a document whose only
  attempt failed. Fixed by also requiring `current_version_id IS NOT NULL` (i.e. some
  version has actually reached `ready`) before treating a re-upload as unchanged. Caught by
  reasoning through the failure path while writing the route, before writing its tests.
- **`@router.post("/documents", status_code=202)` forced 202 on every response, including
  the "unchanged" (200) branch.** FastAPI's per-route `status_code` argument is a fixed
  default applied to *every* successful return from that handler, regardless of which
  response body/model is returned. The upload route returns either `UploadAccepted` (202,
  new/changed content) or `UploadUnchanged` (200, no-op) from the *same* handler, so a single
  fixed `status_code` on the decorator was always wrong for one of the two branches. Caught
  by `tests/integration/test_versioning.py::test_reuploading_identical_bytes_is_a_no_op`,
  which asserted `200` and got `202` — the response *body* was already correct
  (`{"status": "unchanged", ...}` with the right `document_version_id`), which is what made
  this one easy to misdiagnose as a versioning-logic bug before checking the actual DB state
  directly and finding the versioning logic was fine all along. Fixed by removing the fixed
  `status_code` from the decorator and setting `response.status_code` explicitly (200 or
  202) in each branch via an injected `Response` parameter.
- **Real parsing runs got progressively slower (eventually 10+ minutes) within one
  long-lived `--pool=solo` Celery worker process, then went back to normal (~30s) the moment
  the worker was restarted.** `--pool=solo` was required for Windows compatibility (Celery's
  default prefork pool needs `fork()`, unavailable on Windows) — but it also means every task
  runs sequentially in the *same* long-lived Python process, with no prefork-style recycling
  between tasks. The worker log timeline made this unambiguous: two consecutive real jobs
  early in the process's life completed in ~32s each; after ~8 real jobs in that same
  process, a job stalled for 4-16 minutes with zero HTTP/DB activity logged during
  `ComplexPDFParser`'s parsing stage specifically (CPU usage and process count were checked
  at the time and ruled out general system contention or a duplicate worker). Restarting the
  worker process — no code change — immediately brought the same test back to a clean 121s
  run. Most likely cause: some resource (PyMuPDF document handles, Tesseract subprocess
  handles, or temp-file-handle pressure from `ComplexPDFParser`'s per-page/per-image writes)
  accumulates across tasks in a process that's never recycled. Not fully root-caused, and not
  fixed at the code level in this spec — flagging as a real operational finding for whoever
  runs this in a longer-lived environment: **the worker process should be periodically
  recycled** (e.g. Celery's `--max-tasks-per-child`-equivalent isn't available for the solo
  pool, so recycling would need to be external — a supervisor that restarts the worker every
  N tasks or on a schedule). For this spec's own verification,
  `tests/integration/test_upload_and_ingest.py::_poll_job_until_terminal`'s default timeout
  was raised from 240s to 600s so a single slow run doesn't fail the suite outright, but the
  real fix (worker recycling) is a deployment/ops concern for a later phase, not something
  `packages/ingestion` itself can solve.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| RLS bootstrap-ordering trap for document/job detail routes | Would have been High if not caught before coding | High (500s, identical to `011`'s two prior incidents) | Resolved in this plan by nesting every route under `/workspaces/{id}/...` before any code is written |
| RLS bootstrap-ordering trap for the Celery worker resolving its own job's tenant | Would have been High if not caught before coding | High (worker could never read its own job row) | `tenant_id` passed explicitly as a task argument by the enqueuer instead of looked up by the worker — see Implementation findings |
| Large/image-heavy PDFs exceed Celery task time limits or worker memory | Medium | Medium | Explicit Celery task soft/hard time limits set in `tasks.md`; full streaming/chunked parsing is out of scope (matches "migration, not rewrite") |
| Qdrant/Memurai native-Windows setup has rough edges undocumented for this exact combo | Medium | Low (one-time local setup cost) | Same native-install-then-verify-for-real approach already used successfully for Postgres/MinIO/Keycloak |
| This is the first spec with a real per-call cost (OpenAI embeddings) | Certain | Low $ (embeddings are fractions of a cent per document) but a real first | Flagged explicitly for approval below — every prior spec was free/local-only |

## Alternatives considered

- **Bare `/documents/{id}`, `/jobs/{id}` paths** (matching `09`'s table literally), solving
  the RLS bootstrap problem with a new non-RLS lookup table mapping `document_id ->
  workspace_id` — rejected: adds a denormalized table purely for URL aesthetics, when
  nesting under `/workspaces/{id}/` is simpler, consistent with the rest of this spec's
  routes, and costs API consumers nothing (they already have `workspace_id` in context in
  every realistic flow — this API has no UI yet, and even the eventual UI reaches a document
  by first navigating into a workspace).
- **SSE/WebSocket job-status push now** — rejected per spec Non-goals; polling satisfies the
  assignment's stated requirement with far less new infrastructure.
- **Direct OpenAI SDK instead of `langchain-openai`/`langchain-qdrant`** — considered, since
  this spec doesn't need the rest of LangChain; rejected in favor of matching V1's proven
  code as closely as possible (spec Constraints: "migration, not rewrite"). Revisit if/when
  `packages/retrieval`/`packages/generation` land and a direct-SDK approach turns out cleaner
  there anyway.

## New dependencies

- `celery`, `redis` (client) — job queue.
- `qdrant-client` — vector store, used **directly** (not via `langchain-qdrant`, despite V1
  using it) — see Implementation findings for why.
- `langchain-openai` — `OpenAIEmbeddings`, matching V1 (dense embeddings only; no chat/LLM
  call in this spec).
- `langchain-core`, `langchain-text-splitters` — `Document` model, `RecursiveCharacterTextSplitter`, matching V1.
- `pymupdf`, `pdfplumber`, `pytesseract`, `pillow`, `pandas`, `tabulate` — parsing, matching
  V1 (version-flexible pins, not exact copies of the prototype's lockfile, to avoid conflicts
  with this repo's existing `uv.lock`).
- `structlog` — for the new minimal `packages/observability`.
- **System dependency, not a Python package:** Tesseract OCR engine must be installed
  natively (matching V1's `TESSERACT_PATH` env var pattern) — `pytesseract` is just a wrapper
  around the system binary.

## Config additions

`infra/.env.example` gets: `QDRANT_URL=http://localhost:6333`, `QDRANT_API_KEY=` (blank,
local dev has no auth), `QDRANT_COLLECTION_NAME=mm_rag_v1`, `OPENAI_API_KEY=` (blank — **the
first real, paid provider key this repo needs**), `OPENAI_EMBEDDING_MODEL=text-embedding-3-large`,
`OPENAI_EMBEDDING_DIMENSION=3072`, `CELERY_BROKER_URL=redis://localhost:6379/0`,
`CELERY_RESULT_BACKEND=redis://localhost:6379/0`, `TESSERACT_PATH=` (blank, optional if on
PATH, matching V1).

**Explicit callout for approval:** every spec through `011` ran entirely on free/local
infrastructure (native Postgres, MinIO, Keycloak — no paid API calls). This spec is the
first one where end-to-end verification (the embedding/indexing stage specifically) needs a
real `OPENAI_API_KEY` with actual (small) spend — unit tests and the parsing stage don't need
it, but proving the full pipeline reaches `ready` in Qdrant does. Flagging before writing
`tasks.md` so this isn't a surprise mid-implementation.

## Local dev infra (native installs, continuing the Docker-free pattern from `010`/`011`)

- **Qdrant**: official `qdrant-x86_64-pc-windows-msvc` binary from GitHub Releases — same
  install pattern as MinIO (`010`)/Keycloak (`011`): download, run as a standalone process
  pointed at a local data directory.
- **Redis-protocol broker**: Redis itself doesn't support Windows; **Memurai** (Redis-
  protocol-compatible, native Windows service, free for dev use) is a drop-in Celery broker.
  Its free tier has a 10-day uptime cap and a 50%-of-RAM limit — acceptable for local dev,
  worth noting so a restart isn't mistaken for a bug.
- **Tesseract OCR**: native Windows installer (matching how V1 already expects
  `TESSERACT_PATH` to be configurable, since it's not always on `PATH`).
- `infra/docker-compose.yml` gets `qdrant` (already present, unused until now) verified/kept
  and a `worker`/broker note added for parity/documentation, same as `011` did for Keycloak.
