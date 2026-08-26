# Spec: Async Ingestion Pipeline

- **ID:** `020-async-ingestion-pipeline`
- **Roadmap phase:** [08-roadmap.md](../architecture/08-roadmap.md) Phase 3 — Async Ingestion
- **Status:** approved
- **Owner:** Saravanan Shanmugam
- **Date:** 2026-08-24

## Problem statement

The V1 prototype (`src/parsing.py::ComplexPDFParser`, `src/ingestion.py::MultimodalDocumentIngestion`)
parses and embeds a PDF synchronously on the Streamlit request thread — a large or
image-heavy document blocks the UI for the entire parse -> OCR -> table-extract -> chunk ->
embed -> index duration, with no progress visibility beyond a spinner. There is also, as of
today, no way to upload a document through this repo's `apps/api` at all: `010` built the
metadata schema and object storage client, `011` built auth/tenant/workspace scoping, but
`documents`/`document_versions`/`ingestion_jobs` are still empty tables with no writer, and
`packages/ingestion`, `packages/parsing`, and `workers/` are still empty scaffolding. This
spec ports the V1 parsing/ingestion logic behind a real job queue and exposes it through
authenticated API endpoints for the first time, satisfying the assignment's async-processing
requirement (3.2) directly.

## Goals

- An authenticated upload (`workspace` editor+) writes the PDF to object storage and creates
  `documents`/`document_versions`/`ingestion_jobs` rows *synchronously and fast*, then
  enqueues a background job and returns immediately — the request never blocks on parsing.
- A background worker executes the job, advancing `ingestion_jobs.status` through the state
  machine already defined in
  [03-ingestion-workflow.md](../architecture/03-ingestion-workflow.md) §3
  (`queued -> parsing -> chunking -> embedding -> indexing -> ready`, or `failed`), so a
  client polling job status sees real progress instead of a single blocking call.
- Parsing behavior itself — selectable text extraction, per-page OCR, table extraction,
  embedded-image extraction and per-image OCR — is ported into `packages/parsing` with the
  same output shape the V1 prototype already produces; this is a migration behind a queue,
  not a parsing-quality rewrite.
- Ingestion (chunking, dense embedding, Qdrant upsert) is ported into `packages/ingestion`,
  extended to write the full payload shape from
  [02-data-model.md](../architecture/02-data-model.md) §3 (`tenant_id`, `workspace_id`,
  `document_id`, `document_version_id`, `is_current_version`, `visibility`) instead of V1's
  metadata-only payload — so a later retrieval-filtering phase has something real to filter
  on, even though this spec doesn't add query-time filtering itself.
- Content-hash-based versioning per `03-ingestion-workflow.md` §5: an identical re-upload is
  a no-op (no new version, no job enqueued); a changed upload creates a new
  `document_versions` row and job, and the document keeps serving its previous ready
  version's chunks until the new version reaches `ready`.
- Failed jobs record `failure_stage`/`failure_reason`, retry with backoff for transient
  failures, and never leave a document worse off than before the failed upload (previous
  ready version, if any, keeps serving).
- New `apps/api` endpoints for upload, document listing/detail/versions, and job status —
  gated by the same `require_workspace_role` machinery `011` already built (no new auth
  mechanism).

## Non-goals

- No vision captioning of images or table-intelligence upgrades — `03-ingestion-workflow.md`
  §3's stage description mentions vision captioning as part of "parsing," but
  `08-roadmap.md` explicitly places that in Phase 6
  (`050-059`, after hybrid retrieval exists to benefit from it). This spec keeps V1's
  OCR-only image/table handling as baseline and defers captioning — the architecture-doc
  inconsistency this reveals gets fixed in `plan.md`.
- No hybrid/sparse retrieval, RRF fusion, or reranking (Phase 5, `040-049`) — indexing here
  produces the same dense-vector shape V1 already does, with an extended payload only.
- No retrieval-time tenant/ACL query filtering (Phase 4, `030-039`) — this spec writes the
  payload fields Phase 4 will filter on, but adds no query/chat endpoint at all yet.
- No chat/generation endpoints (`packages/generation` stays untouched) — this spec is
  upload/ingest/status only.
- No page-level incremental re-embedding within a changed document — already explicitly
  deferred to a future spec in `03-ingestion-workflow.md` §5.
- No SSE/WebSocket push for job status — polling `GET /jobs/{id}` only. This satisfies the
  assignment's stated requirement (visibility into
  `uploaded/parsing/chunking/indexing/ready`); push is a nice-to-have, not baseline.
- No document deletion endpoint — only create/list/read/version-history. Deletion is
  deferred to whichever spec first needs it, same reasoning `011` used for tenant/workspace
  deletion.

## User-facing behavior

No UI yet (`apps/UI` doesn't exist); observable behavior is API-consumer-level:

- A client with workspace `editor`+ role `POST`s a PDF to a workspace's documents endpoint
  and receives `202 Accepted` + a job id within a couple seconds, regardless of the PDF's
  size or page count.
- Polling the job's status endpoint shows it advance through
  `queued -> parsing -> chunking -> embedding -> indexing -> ready` (or `failed` with a
  reason) as the worker processes it.
- Once `ready`, the workspace's document list shows the document with its current version;
  a document's version-history endpoint shows prior versions.
- Re-uploading byte-identical content returns success with no new version and no new job.
- Re-uploading changed content creates a new version and a new job; chat/retrieval (once
  those exist) would keep serving the old version's chunks until the new one is `ready`.
- A failed job is visible as `failed` with a reason; the document's previously-`ready`
  version, if any, is untouched.

## Acceptance criteria

- [ ] Upload endpoint returns `202` + job id without waiting for parsing to start, for PDFs
      of varying size (tested with a small and a multi-page/image-heavy PDF).
- [ ] Within the upload request, a `documents` row, a `document_versions` row, and an
      `ingestion_jobs` row (`status = queued`) exist, and the PDF bytes are durably in object
      storage — all before the response is returned.
- [ ] A background worker picks up the job and `ingestion_jobs.status` visibly transitions
      through every stage in `03-ingestion-workflow.md` §3, observable via the job-status
      endpoint.
- [ ] On success: Qdrant contains one point per chunk/table/image with the full payload
      shape from `02-data-model.md` §3; `documents.status` and `documents.current_version_id`
      are updated; `document_versions.is_current` is `true` for the new version.
- [ ] Re-uploading identical bytes (same `content_hash`) creates no new
      `document_versions` row and enqueues no job.
- [ ] Re-uploading changed bytes creates a new `document_versions` row
      (`version_number + 1`) and a new job; `is_current_version` only flips in Qdrant (and
      `superseded_at` is set on the old version) after the new job reaches `ready` — the
      document serves the old version's chunks the entire time in between.
- [ ] A job that fails (e.g. a corrupt/unparseable PDF) sets `status = failed` with
      `failure_stage`/`failure_reason` populated, increments `retry_count` per the retry
      policy, and leaves the document's previously-`ready` version (if any) completely
      unaffected.
- [ ] Every new endpoint (upload, list documents, get document, list versions, get job) is
      gated by `require_workspace_role` from `011` — an unauthorized caller gets the same
      401/403/404 policy already established, not a new/different one.
- [ ] Parsing output (selectable text, page OCR text, extracted tables, extracted images +
      image OCR text) matches the V1 prototype's `ComplexPDFParser` behavior on the same
      input PDF — this is a behavior-preserving port, verified by comparing output shape/
      content against the prototype's own output for a fixed test PDF.
- [ ] `tests/unit` and `tests/integration` cover the above against real Postgres, MinIO,
      Qdrant, and the job broker (no mocks), per this project's established testing
      convention.

## Constraints

- Builds on `packages/db` (`010`) and `packages/auth`/`apps/api` (`011`) exactly as they
  exist today — new document/job routes reuse `require_workspace_role`, not a new auth path.
- Parsing behavior/library choices (PyMuPDF, pdfplumber, pytesseract) are preserved from the
  V1 prototype as-is; this spec is an infrastructure migration, not a parsing-quality change.
- Object storage keys use the scheme already fixed in `010`'s `plan.md` (content-hash-
  addressed, tenant/workspace/document/version-scoped) — no new key scheme invented here.
- Local dev should remain Docker-free-capable where practical, consistent with how `010` and
  `011` were verified (native Postgres, MinIO, Keycloak) — Qdrant ships an official native
  Windows binary and Redis has a native-Windows-compatible option (Memurai), so this is
  achievable; exact setup is a `plan.md` decision.
- No provider API keys (OpenAI embeddings) touched by `apps/api`'s request path — the
  embedding call happens inside the background worker process only, consistent with
  `06-security-model.md` §6 ("Provider API keys are held by the backend services only").
- Python 3.12, `uv`-managed, per `CLAUDE.md`. `packages/parsing` and `packages/ingestion`
  follow the same `DocumentPortalException`-wrapping, no-direct-logging convention as
  `packages/db`/`packages/storage`/`packages/auth`.

## Open questions

None blocking — resolved during spec research:

- **Vision captioning ordering.** Resolved in favor of `08-roadmap.md`'s explicit phasing
  (deferred to Phase 6); `03-ingestion-workflow.md` gets corrected in `plan.md` to stop
  implying captioning happens during this phase's "parsing" stage.
- **Job broker on native Windows.** Redis itself doesn't officially support Windows, but
  Memurai (a native-Windows, Redis-protocol-compatible service, free for dev use) is a
  drop-in Celery broker. Qdrant publishes an official `windows-msvc` binary via GitHub
  Releases, same install pattern already used for MinIO/Keycloak. Concrete versions/setup
  steps are a `plan.md` decision, not an open question blocking spec approval.
