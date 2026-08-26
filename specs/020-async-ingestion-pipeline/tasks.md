# Tasks: Async Ingestion Pipeline

- **Plan:** [plan.md](plan.md) (approved 2026-08-24)
- **Status:** done — 89/89 tests pass (unit + integration) against real local Postgres 16,
  MinIO, Keycloak 26.7.2, Qdrant 1.19.0, Memurai (native installs, not Docker), and a real
  `OPENAI_API_KEY`.

Work top to bottom. Each group should leave the system in a runnable state. Check items off
with `- [x]` as completed; do not delete or renumber finished items.

Local verification uses native installs (no Docker), continuing the pattern from
`010`/`011`: PostgreSQL 16, MinIO, and Keycloak are already running; this spec adds native
Qdrant, Memurai (Redis-protocol broker), and Tesseract OCR.

## Group 0 — Test fixture

- [x] Copy a real multi-page PDF (with text, a table, and an embedded image) into
      `tests/fixtures/` from the V1 prototype's `data/` dir, for use by parsing/ingestion
      tests — files: `tests/fixtures/sample.pdf` — 1.5MB, copied from
      `Client_Contracts_Policies_and_Incident_Records.pdf`.

## Group 1 — Local infra: Qdrant, Memurai, Tesseract + config

- [x] Install Qdrant natively (official `windows-msvc` binary, v1.19.0, from GitHub
      Releases), run as a standalone process against a local data directory — verify:
      `GET http://localhost:6333/collections` responds `{"result":{"collections":[]}...}`.
- [x] Install Memurai (Redis-protocol-compatible, native Windows service, v4.1.2 via
      `winget`) as the Celery broker — verify: raw `PING` over the socket on `localhost:6379`
      returns `+PONG`.
- [x] Install Tesseract OCR natively (v5.5.3 via `winget`) — verify: `tesseract --version`
      runs; already on `PATH` at `C:\Program Files\Tesseract-OCR\tesseract.exe`, so
      `TESSERACT_PATH` stays blank.
- [x] Add `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION_NAME`, `OPENAI_API_KEY`,
      `OPENAI_EMBEDDING_MODEL`, `OPENAI_EMBEDDING_DIMENSION`, `CELERY_BROKER_URL`,
      `CELERY_RESULT_BACKEND`, `TESSERACT_PATH` to `infra/.env.example` and `infra/.env` —
      files: `infra/.env.example` — `OPENAI_API_KEY` copied from the sibling V1 prototype
      repo's `.env` into `infra/.env` per explicit user direction (never printed to a
      transcript; copied file-to-file via a script).
- [x] `qdrant` service block in `infra/docker-compose.yml` bumped to `v1.19.0` to match the
      native install; `redis` block annotated noting Memurai is used natively instead
      (Redis itself doesn't support Windows) — files: `infra/docker-compose.yml`.
- [x] New Python dependencies in `pyproject.toml`: `celery`, `redis`, `qdrant-client`,
      `langchain-qdrant`, `langchain-openai`, `langchain-core`, `langchain-text-splitters`,
      `pymupdf`, `pdfplumber`, `pytesseract`, `pillow`, `pandas`, `tabulate`, `structlog`,
      `python-multipart` (needed for FastAPI file uploads, not in the original plan list but
      required for Group 6's upload endpoint) — files: `pyproject.toml` — `uv sync` succeeded,
      57 packages installed.

## Group 2 — `packages/exceptions` + `packages/observability`

- [x] `packages/exceptions/parsing.py`: `ParsingError(DocumentPortalException)` — files:
      `packages/exceptions/parsing.py` — verify: unit test passes.
- [x] `packages/exceptions/ingestion.py`: `IngestionError(DocumentPortalException)` — files:
      `packages/exceptions/ingestion.py` — verify: unit test passes.
- [x] `packages/observability/structured_logging.py` (renamed from the planned `logging.py`
      — that name shadows the stdlib `logging` module and confused the linter's import
      resolution): `configure_logging()`, `get_logger()` — `structlog` setup,
      `snake_case_event_name` + keyword fields per `CLAUDE.md` — files:
      `packages/observability/structured_logging.py`, `packages/observability/__init__.py` —
      verify: 2 unit tests pass (structured JSON output, level filtering).

## Group 3 — `packages/parsing`

- [x] `packages/parsing/pdf_parser.py`: `ComplexPDFParser`, ported from the V1 prototype's
      `src/parsing.py` — same public API (`parse(save_output=...) ->
      {pages, images, tables, documents, output_dir}`), same libraries, exceptions wrapped as
      `ParsingError` instead of the prototype's exception type, no direct logging (caller
      logs) — `save_output` default flipped `True -> False` (workers don't need local JSON
      debug dumps; still supported for manual debugging) — files:
      `packages/parsing/pdf_parser.py`, `packages/parsing/__init__.py` — verify: 4 unit tests
      pass against the real `tests/fixtures/sample.pdf` (non-empty pages/documents, at least
      one table or image extracted, page documents carry both selectable and OCR text,
      `save_output=True` writes the debug JSON files) — real Tesseract, real PyMuPDF/
      pdfplumber, no mocks (~89s, dominated by real OCR across 4 full re-parses).

## Group 4 — `packages/ingestion`

- [x] `packages/ingestion/versioning.py`: `content_hash(bytes) -> str` (sha256, matching
      `010`'s storage-key scheme), `is_unchanged(new_hash, current_hash) -> bool` — files:
      `packages/ingestion/versioning.py` — verify: 4 unit tests pass.
- [x] `packages/ingestion/qdrant_setup.py`: `ensure_collection(client, collection_name,
      vector_size)` — creates the collection + payload indexes (`tenant_id`, `workspace_id`,
      `document_id`, `document_version_id`, `is_current_version`, `content_type`,
      `page_number`) from `02-data-model.md` §3 if missing — files:
      `packages/ingestion/qdrant_setup.py` — verify: Group 7 integration tests (needs real
      Qdrant).
- [x] `packages/ingestion/pipeline.py`: chunking (ported from
      `MultimodalDocumentIngestion.prepare_documents`/`_split`), dense embedding
      (`langchain-openai`), Qdrant upsert with the full **flat** tenant-scoped payload
      (writing points directly via `qdrant_client`, not `langchain-qdrant` — see plan.md
      "Implementation findings"), image upload to object storage (local temp path ->
      `packages.storage` key), version-supersession (old version's points get
      `is_current_version = false`, never deleted), and `run_ingestion(job_id, tenant_id,
      session=..., ...)` advancing `ingestion_jobs.status` through
      `parsing -> chunking -> embedding -> indexing -> ready` (or `failed` with
      `failure_stage`/`failure_reason`/`retry_count`) — files:
      `packages/ingestion/pipeline.py`, `packages/ingestion/__init__.py` — also added
      `packages/auth/context.py::set_tenant_scope_sync` (`local` param on both sync/async
      variants — see plan.md) since the worker needs session-scoped, not transaction-scoped,
      RLS GUC persistence across this function's multiple commits — verify: Group 7
      integration tests (needs real Postgres + MinIO + Qdrant + OpenAI key).

## Group 5 — `workers/celery_app.py`

- [x] Celery app instance (`packages/ingestion/config.py::Settings` for broker/result-backend
      URLs, matching the pydantic-settings convention used everywhere else in this repo) +
      one task, `run_ingestion_job(job_id: str, tenant_id: str)` (`tenant_id` passed by the
      enqueuer, not looked up — see plan.md), with explicit soft/hard time limits (10min/11min)
      and Celery-level autoretry (3 attempts, exponential backoff up to 10min, matching the
      spirit of `03-ingestion-workflow.md`'s retry policy) — files: `workers/celery_app.py`,
      `workers/__init__.py` — verify: worker started via `celery -A workers.celery_app worker
      --pool=solo` (prefork doesn't work on Windows), connected to Memurai
      (`redis://localhost:6379/0`), task `workers.celery_app.run_ingestion_job` registered
      and ready.

## Group 6 — `apps/api` routers

- [x] `apps/api/schemas/documents.py`: `DocumentOut`, `DocumentVersionOut`,
      `UploadAccepted`, `UploadUnchanged` — files: `apps/api/schemas/documents.py`.
- [x] `apps/api/schemas/jobs.py`: `JobOut` — files: `apps/api/schemas/jobs.py`.
- [x] `apps/api/routers/documents.py`: `POST /workspaces/{workspace_id}/documents` (upload —
      validates PDF magic bytes + content-type, 413/415 on bad input, writes object storage
      + Postgres rows, computes `content_hash`, no-ops on unchanged content — but only when
      `current_version_id IS NOT NULL`, see plan.md's "Implementation findings" for why that
      guard matters — enqueues a Celery task on change, returns `202`/`200` per plan.md's API
      contract; document identity across uploads resolved by same-filename-in-workspace, per
      plan.md), `GET /workspaces/{workspace_id}/documents`,
      `GET /workspaces/{workspace_id}/documents/{document_id}`,
      `GET /workspaces/{workspace_id}/documents/{document_id}/versions` — all via
      `require_workspace_role` from `011` — files: `apps/api/routers/documents.py`.
- [x] `apps/api/routers/jobs.py`: `GET /workspaces/{workspace_id}/jobs/{job_id}` — files:
      `apps/api/routers/jobs.py`.
- [x] Registered both routers in `apps/api/main.py` — files: `apps/api/main.py` — verified:
      `app.openapi()` lists all 4 new routes exactly matching plan.md's API contract table.

## Group 7 — Integration tests (require real Postgres, MinIO, Qdrant, Memurai, Keycloak,
## and a real `OPENAI_API_KEY`)

- [x] `tests/integration/test_upload_and_ingest.py`: authenticated upload of
      `tests/fixtures/sample.pdf` -> `202` + job id -> poll job status until `ready` (or
      timeout) -> assert Qdrant has points with the correct tenant-scoped payload -> assert
      `documents`/`document_versions` rows match — files:
      `tests/integration/test_upload_and_ingest.py` — **PASSED** against real Postgres/MinIO/
      Qdrant/Keycloak/Memurai and a real `OPENAI_API_KEY`.
- [x] `tests/integration/test_versioning.py`: re-upload identical bytes -> no new version, no
      job; re-upload changed bytes -> new version + job -> old version keeps serving until
      the new one reaches `ready`, then `is_current_version` flips and `superseded_at` is set
      — files: `tests/integration/test_versioning.py` — **PASSED** (2/2). Caught and fixed a
      real bug along the way: the upload route's `status_code=202` decorator argument forced
      202 on the "unchanged" (200) branch too — see plan.md's Implementation findings. Also
      surfaced a worker-process resource-accumulation issue under `--pool=solo` (also
      documented there) — mitigated for test purposes by a longer poll timeout, flagged as a
      real ops concern for later, not a `packages/ingestion` bug.
- [x] `tests/integration/test_ingestion_failure.py`: enqueue a job for a corrupt/unparseable
      PDF -> job reaches `failed` with `failure_stage`/`failure_reason` set, `retry_count`
      incremented, and (if a prior ready version existed) that version is untouched — files:
      `tests/integration/test_ingestion_failure.py` — **PASSED** (2/2), including the
      content_hash_current retry-not-short-circuit fix.
- [x] `tests/integration/test_document_routes_rbac.py`: document/job routes are gated by
      `require_workspace_role` exactly like `011`'s existing routes (401/403/404 policy) —
      files: `tests/integration/test_document_routes_rbac.py` — **PASSED** (5/5).

## Verification (end of increment)

- [x] All acceptance criteria in `spec.md` satisfied and verified against real services
      (not mocks), per this project's stated testing preference.
- [x] `uv run pytest tests/unit` passes without any live services.
- [x] `uv run pytest tests/integration` passes against real local Postgres/MinIO/Qdrant/
      Memurai/Keycloak and a real `OPENAI_API_KEY`.
- [x] `specs/README.md` status for `020-async-ingestion-pipeline` updated to `done`.
- [x] `03-ingestion-workflow.md` and `09-repo-and-module-structure.md` deltas from plan.md
      applied.
