# Asynchronous Ingestion & Versioning Workflow

- **Status:** approved baseline

> ⚠️ **Single-tenant as-built ([`specs/012`](../012-single-tenant-simplification/spec.md)).**
> The **indexing** step writes a `workspace_id` payload (no `tenant_id`); object-storage keys
> are `{workspace_id}/{document_id}/…`. The worker no longer sets an RLS GUC.

## 1. Current behavior (V1, to be replaced)

`ui/app.py` calls `ComplexPDFParser.parse()` and `MultimodalDocumentIngestion.ingest_pdf()`
synchronously on the Streamlit request thread — a large PDF blocks the UI for the entire
parse+OCR+embed+index duration. The only "async-like" behavior today is the resume logic in
`ui/app.py` (`try_restore_parsed_state`, `try_restore_index_state`): if a manifest/sha256
match is found, parsing/embedding is skipped. That resume idea is correct and is preserved
below as versioning — it just needs to move off the request thread and into a real job.

## 2. Target flow

```
Upload -> Object Storage -> create documents/document_versions/ingestion_jobs rows
       -> enqueue job (Celery, Redis broker) -> return 202 + job_id immediately
       -> [worker] parsing -> chunking -> embedding -> indexing -> ready
       -> Web UI polls GET /jobs/{id} or subscribes over SSE/WebSocket
```

The API's document-upload endpoint never runs parsing itself. It only: validates the upload,
writes bytes to object storage, computes `content_hash`, writes the Postgres rows, enqueues
the job, and returns. This satisfies assignment 3.2 directly.

## 3. Status state machine

`ingestion_jobs.status` transitions:

```
queued -> parsing -> chunking -> embedding -> indexing -> ready
   |         |           |           |            |
   +---------+-----------+-----------+------------+--> failed (failure_stage records where)
```

- **queued**: job row created, sitting in Celery broker, not yet picked up.
- **parsing**: `ComplexPDFParser` equivalent running — text/OCR extraction, table extraction,
  image extraction with OCR (matching V1's behavior as ported by
  `020-async-ingestion-pipeline`), plus vision captioning of images
  (`05-multimodal-strategy.md` §1, `050-vision-captioning`) and table intelligence —
  summarization, schema inference, normalized-row storage, row-group chunking
  (`05-multimodal-strategy.md` §2, `051-table-intelligence`) — both implemented as
  post-processing passes in `packages/ingestion/pipeline.py::run_ingestion` after
  `ComplexPDFParser.parse()` returns, still within this stage, not a new one.
- **chunking**: `RecursiveCharacterTextSplitter` (as in `src/ingestion.py::_split`) applied to
  text content; tables/images kept as single chunks as today.
- **embedding**: dense (OpenAI) + sparse (BM25/SPLADE via FastEmbed) vectors computed per
  chunk.
- **indexing**: chunks upserted into Qdrant with full tenant/workspace/ACL payload; on
  success, `document_versions.is_current` flips and superseded points are marked
  non-current (see §5).
- **ready**: `documents.status = ready`, `documents.current_version_id` updated. UI unblocks
  chat for this document.
- **failed**: `failure_stage` + `failure_reason` recorded; `retry_count` incremented. The
  document stays on its previous ready version if one exists — a failed re-ingestion must
  never leave a document worse off than before the upload.

Each transition is a Postgres update in the same job, and the API exposes it as a webhook/SSE
event so the UI can render `uploaded / parsing / chunking / indexing / ready` (assignment
3.2's exact requirement) instead of a blocking spinner.

## 4. Failure and retry handling

- Celery task retries with exponential backoff (e.g. 3 attempts: 30s, 2m, 10m) for
  transient failures (OCR engine timeout, embedding API rate limit, Qdrant unavailable).
- Non-retryable failures (corrupt PDF, unsupported format) fail immediately with a
  user-facing `failure_reason` and no retry.
- After max retries, the job is `failed` and routed to a dead-letter queue for manual/ops
  inspection; the document keeps serving its last-`ready` version if any.
- Partial extraction failures (e.g. OCR fails on one page, table extraction throws on one
  page — both already handled today with warning logs in `src/parsing.py`) do **not** fail
  the whole job; they degrade gracefully (empty OCR text / skipped table) and are recorded as
  warnings on the job for visibility, matching existing `logger.warning(...)` behavior in
  `run_ocr_on_image` and `extract_tables`.

## 5. Versioning and incremental ingestion (assignment 3.9)

- On upload, compute `content_hash = sha256(bytes)` before touching object storage (mirrors
  `ui/app.py::file_fingerprint` / `fingerprint_file`, already correct).
- If `content_hash` matches `documents.content_hash_current` for that `document_id`: **no
  new version is created, no job is enqueued** — this is the existing "restore" behavior in
  `ui/app.py`, just moved server-side and made authoritative instead of best-effort local
  file detection.
- If it differs: create a new `document_versions` row (`version_number + 1`), enqueue a full
  ingestion job for that version, and only after it reaches `ready` do we flip
  `is_current_version` — the old version's Qdrant points get `is_current_version = false`
  (kept, not deleted, so citations in old conversation history still resolve) and
  `document_versions.superseded_at` is set.
- **Full rebuild is avoided at the workspace level always** — a document changing never
  touches another document's chunks (this is already true today since deletion is scoped by
  `metadata.document_id` in `_delete_existing_document`).
- **Page-level incremental re-embedding** (avoiding re-embedding unchanged pages within a
  changed document) is a stretch goal, not baseline: it requires per-page content hashing
  during parsing and a diff step before chunking. Track it as a follow-up spec
  (`specs/030-page-level-incremental-reingest/`) rather than baseline scope — baseline scope
  is "unchanged document = skip entirely, changed document = full re-parse of that one
  document," which already satisfies 3.9's stated requirement ("skip unnecessary parsing and
  embedding" at the document level; "update... only the relevant document data rather than
  rebuilding the entire workspace").

## 6. Related docs

- `01-system-architecture.md` §4 for the end-to-end request/data flow diagram
- `02-data-model.md` for the `ingestion_jobs` / `document_versions` schema
- `05-multimodal-strategy.md` for what happens inside the `parsing` stage for images/tables
