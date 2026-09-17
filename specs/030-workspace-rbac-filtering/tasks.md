# Tasks: Workspace RBAC Filtering

- **Plan:** [plan.md](plan.md) (approved 2026-09-14)
- **Status:** done — full live stack (Postgres, Memurai, Keycloak, Qdrant Cloud, MinIO,
  Celery worker) came online over the course of implementation and every integration test
  now passes against it, real `OPENAI_API_KEY` included. Two real RLS gaps were found and
  fixed along the way that code reading alone had missed: the Celery worker never set the
  RLS scope at all (would have broken all async ingestion), and API-key authentication was
  completely broken by RLS (found only once Keycloak was actually running) — see `plan.md`'s
  Deviations section for both. MinIO itself needed a workaround: the open-source project's
  standard download channels are discontinued (archived April 2026), but MinIO's own GitHub
  releases from before the archival still host signed Windows binaries — verified against
  the published SHA256 before running. A `/simplify` cleanup pass ran after the feature was
  functionally complete; all tests stayed green through it.

Work top to bottom. Each group should leave the system in a runnable state. Check items off
with `- [x]` as completed; do not delete or renumber finished items.

## Group 1 — Postgres RLS

- [x] Add `packages/db/rls.py::set_workspace_scope(session, workspace_id)` — issues
      `SELECT set_config('app.current_workspace_id', :wid, true)` via a parameterized
      query. — files: `packages/db/rls.py` — verify: `uv run pytest tests/unit/test_db_rls.py`
      (4 passed — mocks `session.execute`, asserts call shape/params, and the failure-wrap).
- [x] Write migration `0002_workspace_rls.py`: `ENABLE ROW LEVEL SECURITY` +
      `FORCE ROW LEVEL SECURITY` + one `CREATE POLICY ... USING/WITH CHECK
      (workspace_id = current_setting('app.current_workspace_id', true)::uuid)` on
      `documents`, `api_keys`, `audit_log`; the join/`EXISTS`-based equivalent on
      `document_versions` and `ingestion_jobs` (per `plan.md`). Down-migration drops the
      policies and disables RLS. — files:
      `packages/db/migrations/versions/0002_workspace_rls.py` — verify:
      `alembic upgrade head` then `alembic downgrade -1` then `alembic upgrade head` all ran
      clean against the native local Postgres (`postgresql-x64-16` Windows service); confirmed
      `relrowsecurity`/`relforcerowsecurity` true on the 5 protected tables and false on
      `workspaces`/`workspace_members` via a direct `pg_class` query at each step.
- [x] Wire `set_workspace_scope` into `apps/api/deps/rbac.py::require_workspace_role` —
      called right after role resolution succeeds, on both the JWT and API-key branches,
      before returning `WorkspaceAccess`. — files: `apps/api/deps/rbac.py` — verify:
      `uv run pytest tests/unit/test_auth_rbac.py` still passes (53/53 full unit suite green;
      no behavior change to the function's return value/exceptions, only a new side effect).
- [x] New integration test: connect directly to Postgres (bypassing `apps/api` entirely) as
      the same app DB user, set the workspace GUC to workspace X via `set_workspace_scope`,
      and assert cross-workspace rows are invisible for each of the five protected tables;
      also assert a genuinely unset GUC (fresh raw `psycopg` connection, not a pooled
      SQLAlchemy one — see file comment for why that distinction matters) returns zero rows
      (fail-closed). — files: `tests/integration/test_rls.py` — verify:
      `uv run pytest tests/integration/test_rls.py` — 5 passed, against real Postgres only.
- [x] **Found during verification, not in the original plan:** `packages/ingestion/pipeline.py`
      (the Celery worker) writes to `ingestion_jobs`/`document_versions`/`documents` entirely
      outside `apps/api` — it never called anything that would set the RLS GUC, so migration
      `0002` would have silently broken every async ingestion job (the very first query,
      `session.get(IngestionJob, job_id)`, would return nothing). Fixed: added
      `packages/db/rls.py::set_workspace_scope_sync` (session-scoped `is_local=false`, not
      transaction-local — `run_ingestion` commits multiple times per job, which would discard
      a transaction-local value after the first commit); threaded `workspace_id` through
      `apps/api/routers/documents.py`'s `run_ingestion_job.delay(job_id, workspace_id)` ->
      `workers/celery_app.py::run_ingestion_job` -> `packages/ingestion/pipeline.py::run_ingestion`,
      which now sets the scope as its first action. See `plan.md`'s "Deviations found during
      implementation". — files: `packages/db/rls.py`, `packages/ingestion/pipeline.py`,
      `workers/celery_app.py`, `apps/api/routers/documents.py` — verify: covered by
      `test_db_rls.py`'s sync-variant cases; full end-to-end verification needs a live
      Qdrant/MinIO/Keycloak stack, not available in this environment (see Verification notes
      at the end of this file) — re-run `tests/integration/test_upload_and_ingest.py` and
      `test_versioning.py` once that stack is up, before calling this phase done.
- [x] **Found during verification:** `tests/integration/test_db_roundtrip.py` writes to
      `documents`/`document_versions` directly via the ORM (no `apps/api`), so it hit the same
      gap — regressed under RLS until fixed to call `set_workspace_scope` itself first,
      mirroring what a real request does. Its stale "no Row-Level Security" docstring was
      also corrected. — files: `tests/integration/test_db_roundtrip.py` — verify:
      `uv run pytest tests/integration/test_db_roundtrip.py tests/integration/test_rls.py` —
      6 passed.
- [x] **Found once Keycloak came online (not from code reading):** API-key authentication
      was completely broken by RLS. `apps/api/deps/rbac.py::require_workspace_role`'s
      API-key branch queried the now-RLS-protected `api_keys` table by hash *before* calling
      `set_workspace_scope` — the classic chicken-and-egg gap, missed the first time because
      the JWT branch's first lookup (`workspace_members`) is RLS-exempt, so nothing about
      that code path exercises the bug. Fixed: scope to the path's `workspace_id` (known,
      just not yet verified) before the key lookup — safe, since a key that doesn't exist or
      belongs elsewhere still resolves to `None`. Also fixed `test_audit_log.py`, which had
      the same raw-`db_session`-never-sets-the-GUC issue as `test_db_roundtrip.py` for its
      direct `audit_log` read. See `plan.md`'s Deviations section. — files:
      `apps/api/deps/rbac.py`, `tests/integration/test_audit_log.py` — verify:
      `uv run pytest tests/integration/test_api_keys.py tests/integration/test_audit_log.py`
      — 3 passed (were failing before the fix).
- [x] Run the full existing `011`/`012`/`020` integration suite, minus what needs object
      storage, to confirm RLS doesn't change any currently-passing outcome. — files: none
      (verification only) — verify: `uv run pytest tests/integration/test_document_routes_rbac.py
      tests/integration/test_api_keys.py tests/integration/test_audit_log.py
      tests/integration/test_auth_flow.py tests/integration/test_jit_provisioning.py
      tests/integration/test_rls.py tests/integration/test_db_roundtrip.py` against real
      Postgres + Keycloak — **22/22 passed**. `test_upload_and_ingest.py`/`test_versioning.py`/
      `test_ingestion_failure.py`/`test_storage_roundtrip.py` still need S3 — see Group 4.

## Group 2 — `packages/retrieval` (dense-only search)

- [x] Add `packages/exceptions/retrieval.py::RetrievalError` and export it from
      `packages/exceptions/__init__.py`, following the `IngestionError` pattern. — files:
      `packages/exceptions/retrieval.py`, `packages/exceptions/__init__.py` — verify:
      `uv run pytest tests/unit/test_exceptions.py` passes.
- [x] Add `packages/retrieval/config.py::Settings` mirroring
      `packages/ingestion/config.py`'s shape (`qdrant_url`, `qdrant_api_key`,
      `qdrant_collection_name`, `openai_api_key`, `openai_embedding_model`). — files:
      `packages/retrieval/config.py` — verify: `uv run pytest tests/unit/test_retrieval_config.py`
      — 2 passed.
- [x] Add `packages/retrieval/filters.py::build_workspace_filter(workspace_id)` — returns a
      `qdrant_client.models.Filter` with unconditional `workspace_id` and
      `is_current_version=true` `FieldCondition`s; no other input accepted. — files:
      `packages/retrieval/filters.py` — verify: `uv run pytest
      tests/unit/test_retrieval_filters.py` — 2 passed (constructed filter contents, and that
      the function's signature has exactly one parameter).
- [x] Add `packages/retrieval/dense.py::dense_search(qdrant_client, embeddings,
      collection_name, workspace_id, query, k)` — embeds `query` via
      `embeddings.embed_query`, calls `qdrant_client.query_points` with
      `build_workspace_filter(workspace_id)`, maps hits to a `SearchResult` dataclass
      (`document_id`, `document_version_id`, `filename`, `content_type`, `page_number`,
      `chunk_index`, `table_index`, `image_index`, `image_path`, `text`, `score`), wraps
      failures as `RetrievalError`. — files: `packages/retrieval/dense.py` — verify:
      `uv run pytest tests/unit/test_retrieval_search.py` — 5 passed (fake/mock
      `qdrant_client`+`embeddings`, no live services; filter pass-through, result mapping,
      and both failure-wrap paths).
- [x] Add `packages/retrieval/search.py` as the single public entry point `apps/api` calls,
      composing `dense.py` + a `Settings`-backed Qdrant/embeddings client construction (same
      construction pattern `workers/celery_app.py` uses for `packages/ingestion`). — files:
      `packages/retrieval/search.py` — verify: covered by the unit tests above; end-to-end
      exercise needs a live Qdrant, which isn't available in this environment (see Group 4).

## Group 3 — Ingestion payload amendment + search route

- [x] Add `"text": lc_doc.page_content` to the point payload dict in
      `packages/ingestion/pipeline.py`. — files: `packages/ingestion/pipeline.py` — verify:
      `uv run pytest tests/unit` (65 passed) and confirmed end-to-end against live Qdrant Cloud
      via `test_upload_and_ingest.py`/`test_search_rbac.py` — real points upsert with `text`
      present and are returned by search.
- [x] Add `apps/api/schemas/search.py` (`SearchRequest{query: str (1-2000 chars), k: int =
      8 (1-50)}`, `SearchResultOut`, `SearchResponse`). — files: `apps/api/schemas/search.py`
      — verify: `uv run pytest tests/unit` passes; schema wiring confirmed via the openapi
      check below.
- [x] Add `apps/api/routers/search.py`: `POST /workspaces/{workspace_id}/search`,
      `require_workspace_role("viewer")`, calls `packages.retrieval.search`, returns
      `SearchResponse`. Register the router in `apps/api/main.py`. — files:
      `apps/api/routers/search.py`, `apps/api/main.py` — verify: `app.openapi()['paths']`
      lists `/workspaces/{workspace_id}/search` with `post` alongside all pre-existing routes;
      exercised for real over HTTP by `tests/integration/test_search_rbac.py` (5 passed)
      against the live server.

## Group 4 — Authorization test suite for retrieval

**Unblocked and fully executed.** MinIO's open-source project archived its standard download
channels (dl.min.io returns 410; the latest GitHub release ships no binary assets), but
releases published before the archival still host official, signed Windows binaries —
downloaded `minio.windows-amd64.RELEASE.2025-09-07T16-13-09Z.exe`, verified its SHA256
against MinIO's own published checksum, and ran it natively on port 9000/9001 with the
credentials already in `infra/.env`. Created the `mm-rag-documents` bucket via boto3. Started
a Celery worker (`uv run celery -A workers.celery_app worker --pool=solo`). All 5 tests below
now pass against the real stack (Postgres, Memurai, Keycloak, Qdrant Cloud, MinIO, worker,
real `OPENAI_API_KEY`).

- [x] Extend the two-workspace fixture pattern from `test_document_routes_rbac.py`: ingest a
      real document into workspace A (user1) and a different one into workspace B (user2),
      wait for `ready` (reusing `test_upload_and_ingest.py`'s polling helper). — files:
      `tests/integration/test_search_rbac.py` (new) — verify: passed against the real stack.
- [x] Test: user1 (member of A) searches A → `200`, all `document_id`s in the response
      belong to documents ingested into A. — `test_member_search_scoped_to_own_workspace` —
      passed.
- [x] Test: user1 (not a member of B) searches B → `403`/`404`, response body contains no
      workspace-B identifiers. — `test_non_member_search_rejected` — passed.
- [x] Test: unauthenticated search request → `401`. Test: empty `query` / `k=0` / `k=51` →
      `422`. Also added `test_nonexistent_workspace_search_returns_404_not_500` (not in the
      original task list — matches the existing 404-vs-403-indistinguishability pattern
      `test_document_routes_rbac.py::test_document_and_job_routes_404_for_non_member`
      already establishes for other routes). — files: `tests/integration/test_search_rbac.py`
      — all passed (5/5 in this file).

## Group 5 — Existing route audit

- [x] Walk every route in `apps/api/routers/{documents,jobs,api_keys,workspaces}.py`
      against `06-security-model.md` §3-§5 (guard present, role correct, list queries
      filtered, 404-vs-403 indistinguishable, no ID leakage in error bodies).

  **Findings, per file:**
  - `documents.py` (upload/list/get/list_versions): compliant. Guard present with correct
    min role on every route; list/get queries filtered by `access.workspace_id`; 404 for
    missing-or-invisible document, no ID leakage.
  - `jobs.py::get_job`: compliant. Joined query filters by `access.workspace_id`; 404 for
    missing-or-invisible job.
  - `api_keys.py` (create/list/revoke): compliant. `revoke_api_key` scopes its lookup by
    both `key_id` **and** `workspace_id`, so a key ID from another workspace can't be
    revoked by guessing the ID; a missing/foreign key silently no-ops (204) rather than
    404 — strictly *less* information disclosure than the 404 pattern elsewhere, so left
    as-is rather than made falsely "consistent."
  - `workspaces.py::create_workspace`/`list_my_workspaces`: compliant. The two routes with
    no workspace in the path correctly use `get_current_user` instead of
    `require_workspace_role`; `list_my_workspaces` is the one legitimate route that spans
    multiple workspaces (filtered by the caller's own `WorkspaceMember.user_id`, per
    `plan.md`'s Open Question 2 resolution).
  - **`workspaces.py::update_workspace_member_role` and `::remove_workspace_member` — real
    bug found, fixed.** Both did `session.get(WorkspaceMember, ...)` and then used the
    result unconditionally (`member.role = ...`; `session.delete(member)`). A `user_id` with
    no membership row in that workspace crashed with an unhandled 500
    (`AttributeError`/`UnmappedInstanceError`) instead of the clean 404 every other route in
    this audit returns for "not found or not visible." Fixed: both now raise
    `HTTPException(404)` when the lookup returns `None`, matching the established pattern.
    Not a cross-workspace data leak (Postgres FK + the workspace-scoped lookup already
    prevented that), but a real robustness/consistency gap this audit exists to catch.
  - `workspaces.py::add_workspace_member`: noted, not fixed. Adding a non-existent
    `body.user_id` isn't existence-checked before insert — relies on the `users.id` FK
    constraint to reject it, which surfaces as a 500 rather than a clean 4xx. Left out of
    scope: not an isolation/RBAC defect (no data crosses a workspace boundary), just an
    unhandled edge case in a different category from what this audit's acceptance criteria
    (`spec.md`) target.
  — files: `apps/api/routers/workspaces.py` (fix),
  `tests/integration/test_document_routes_rbac.py` (new
  `test_member_role_update_and_removal_404_for_non_member_user_id`, collects cleanly, not
  executed — same Keycloak/Postgres blocker as Group 4) — verify: `uv run pytest
  tests/integration/test_document_routes_rbac.py --collect-only` — 6 tests collected;
  `uv run python -c "from apps.api.main import app"` — imports cleanly, 10 routes.

## Verification (end of increment)

- [x] All `spec.md` acceptance criteria implemented and verified end to end against a real
      stack — the environment gap noted earlier (no Qdrant/MinIO/Keycloak) has been closed
      (see Status line above).
- [x] `uv run pytest tests/unit` passes with no live services — 65 passed (was 53 before
      this phase).
- [x] `uv run pytest tests/integration` passes against real
      Postgres/MinIO/Qdrant(Cloud)/Memurai/Keycloak + a real `OPENAI_API_KEY`, plus a running
      Celery worker — **34/34 green** across every integration test file: `test_rls.py` (5),
      `test_db_roundtrip.py` (1), `test_document_routes_rbac.py` (6, including the new 404
      fix), `test_api_keys.py` (2), `test_audit_log.py` (1), `test_auth_flow.py` (5),
      `test_jit_provisioning.py` (2), `test_storage_roundtrip.py` (2),
      `test_upload_and_ingest.py` (1), `test_versioning.py` (2), `test_ingestion_failure.py`
      (2), `test_search_rbac.py` (5). The Postgres+Keycloak-only run (22 of these) is what
      caught the API-key/RLS bug — running the real auth flow surfaced a gap code reading
      alone had missed.
- [x] `02-data-model.md`, `06-security-model.md`, `04-retrieval-design.md` updated per
      `plan.md`'s Architecture doc deltas.
- [x] `specs/README.md` gains a `030` row; status set to `done`.
