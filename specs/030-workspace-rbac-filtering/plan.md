# Plan: Workspace RBAC Filtering

- **Spec:** [spec.md](spec.md) (approved 2026-09-14)
- **Status:** draft

## Summary

Two independent additions behind the already-working RBAC guard
(`apps/api/deps/rbac.py::require_workspace_role`): (1) workspace-scoped Postgres Row-Level
Security as defense-in-depth, driven by a `set_config('app.current_workspace_id', ...)` call
made once per request right after the caller's role is resolved; and (2) a first,
deliberately minimal `packages/retrieval` package plus a `POST /workspaces/{workspace_id}/
search` route that does dense-vector-only Qdrant search with a server-constructed,
non-optional `workspace_id` filter. A small, explicitly-called-out amendment to `020`'s
ingestion pipeline adds the chunk's source text to the Qdrant payload (it is currently
embedded but never stored), because a search endpoint that returns only metadata and a score
is not independently testable or useful to Phase 5. The existing RBAC guards on
`documents`/`jobs`/`api_keys`/`workspaces` are audited against `06-security-model.md` §3-§5
and found substantially compliant already (see Audit findings) — this plan fixes what the
audit finds, it does not rebuild the guard.

## Architecture doc deltas

| Doc | Change |
|---|---|
| `06-security-model.md` | §4: mark the retrieval-time filter as implemented (`packages/retrieval`, dense-only) instead of not-yet-existing; note hybrid/rerank stages are still Phase 5. §5: narrow the RLS ⚠️ DEFERRED marker — workspace-scoped RLS is now implemented for `documents`/`document_versions`/`ingestion_jobs`/`api_keys`/`audit_log`; `conversations`/`messages`/`message_feedback` stay unprotected (unused by any route yet) with a pointer to whichever spec first adds chat endpoints. |
| `02-data-model.md` | §0: note which tables carry a workspace-scoped RLS policy and that `document_versions`/`ingestion_jobs` are protected via a join-based policy (no new denormalized column) rather than a direct `workspace_id` column. §3: add `text` to the documented Qdrant payload schema. |
| `04-retrieval-design.md` | §1/§6: note dense-only search now exists in `packages/retrieval` as the base Phase 5 extends, matching the "why fuse-then-rerank" section's assumption that a filtered dense leg already exists. |

## Component/module ownership

- `packages/db` — new `rls.py` (the `set_workspace_scope(session, workspace_id)` helper) and
  migration `0002_workspace_rls.py` (DDL only: `ENABLE`/`FORCE ROW LEVEL SECURITY` + `CREATE
  POLICY` on the five tables listed above). No model/column changes.
- `apps/api/deps/rbac.py` — `require_workspace_role` calls `set_workspace_scope` immediately
  after role resolution succeeds, for both the JWT and API-key auth paths, before returning
  `WorkspaceAccess`.
- `packages/retrieval` (new package, first code in it) — `config.py` (Settings, mirroring
  `packages/ingestion/config.py`'s shape: `qdrant_url`, `qdrant_collection_name`,
  `openai_api_key`, `openai_embedding_model`), `filters.py` (builds the mandatory
  `workspace_id` + `is_current_version` Qdrant filter — the one function every later phase's
  filter additions extend), `dense.py` (embeds the query via `OpenAIEmbeddings.embed_query`
  and calls `qdrant_client.query_points`), `search.py` (the public `dense_search(...)` entry
  point `apps/api` calls). Per `09-repo-and-module-structure.md`'s stated target
  ("`packages/retrieval/*` split into dense/sparse/fusion/rerank/filters"), only
  `dense`/`filters` land now; `sparse`/`fusion`/`rerank` are Phase 5.
- `packages/exceptions` — new `retrieval.py` (`RetrievalError`, wrapped at the
  `packages/retrieval` boundary, same pattern as `IngestionError`).
- `apps/api/routers/search.py` (new), `apps/api/schemas/search.py` (new) — the HTTP surface,
  registered in `apps/api/main.py` alongside the existing four routers.
- `packages/ingestion/pipeline.py` — one-line payload addition (`"text":
  lc_doc.page_content`), amending `020`'s pipeline per that spec's own "amendable" clause.

## Data model changes

- **Postgres (migration `0002`, additive, no column/table changes):**
  - `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY` on `documents`, `document_versions`,
    `ingestion_jobs`, `api_keys`, `audit_log`.
  - One policy per table, `USING`/`WITH CHECK` both keyed on
    `current_setting('app.current_workspace_id', true)::uuid`:
    - `documents`, `api_keys`: direct `workspace_id = ...` (both have the column).
    - `audit_log`: `workspace_id = ...` — since every current write site populates
      `workspace_id` (verified: no code path writes a `NULL`-workspace row today), this does
      not need a NULL-handling branch; if a future spec adds a system-level audit event with
      no workspace, that write will need an explicit RLS-bypass path, called out as a risk
      below rather than solved speculatively here.
    - `document_versions`, `ingestion_jobs`: no direct `workspace_id` column (only
      `document_id` — see `02-data-model.md` §0's as-built schema). Policy uses `EXISTS
      (SELECT 1 FROM documents d WHERE d.id = <table>.document_id AND d.workspace_id =
      current_setting(...)::uuid)`. See Alternatives considered for why this isn't a
      denormalized column instead.
  - **Explicitly excluded:** `workspaces`, `workspace_members` — same "bootstrap ordering"
    reasoning `011` used for the old tenant GUC (`02-data-model.md` §2's note): the caller's
    role must be resolved from `workspace_members` *before* the workspace GUC can be set, so
    that table can't itself depend on the GUC. `conversations`, `messages`,
    `message_feedback` — no route reads or writes them yet (confirmed: `apps/api/routers/`
    has no conversation/chat router); RLS for them is deferred to whichever spec first
    implements chat, noted in `02-data-model.md`.
- **Qdrant payload:** add `"text": lc_doc.page_content` to the point payload written by
  `packages/ingestion/pipeline.py` (currently the chunk is embedded but its source text is
  never stored, so nothing downstream — including this phase's own search endpoint — can
  return or display it). No new payload index needed (not a filter field). Existing local
  test fixtures re-ingest cleanly; no production data exists to migrate (`012`'s established
  norm).

## API contract

**`POST /workspaces/{workspace_id}/search`**
- Auth: Bearer JWT or workspace-scoped API key, minimum role `viewer` (same
  `require_workspace_role("viewer")` dependency `documents`/`jobs` GET routes already use).
- Request body: `{"query": "string, 1-2000 chars", "k": int, default 8, max 50}`.
- Response `200`: `{"results": [{"document_id": uuid, "document_version_id": uuid,
  "filename": str, "content_type": "page_text_plus_ocr"|"table"|"image", "page_number":
  int|null, "chunk_index": int|null, "table_index": int|null, "image_index": int|null,
  "image_path": str|null, "text": str|null, "score": float}]}`, ordered by descending score.
- `workspace_id` is taken solely from the path segment and re-validated against
  `workspace_members` by `require_workspace_role` exactly like every other route — it is
  never read from the request body, and the Qdrant filter `packages/retrieval` builds is not
  parameterized by anything else in the request.
- Errors: `401` (no/bad token), `403` (authenticated, not a member / role below `viewer`),
  `422` (empty query / `k` out of range) — same shape as existing routes' error responses.
- The filter always includes `is_current_version = true` in addition to `workspace_id`, so a
  superseded document version's chunks never surface (matches `02-data-model.md` §3's
  `is_current_version` field and how `020`'s versioning already flips it off on supersession).

No other route's contract changes.

## Retrieval / ingestion impact

- New retrieval capability where none existed; no existing retrieval behavior to regress
  (there is no other query path yet).
- Ingestion (`020`) gains one payload field (`text`); embedding call shape, chunking,
  versioning, and job state machine are all unchanged.
- Expected latency: one OpenAI embedding call (~100-300ms) + one Qdrant `query_points` call.
  Not measured formally here — `07-evaluation-observability.md` (Phase 7) is where retrieval
  latency/quality get instrumented; this phase only needs the call to work correctly and
  stay within the authorized set.

## Security / tenancy impact

Yes — this is the plan's whole point, so being explicit:

- **Two independent enforcement layers now exist for Postgres data:** the existing
  application-layer `WHERE workspace_id = ...` (or the `require_workspace_role` guard itself
  for routes with no direct query), plus the new RLS policies, which apply even if a future
  route forgets the application-layer filter — proven by a test that queries with the
  workspace GUC set correctly but the *application* filter deliberately removed/wrong, using
  a raw connection that bypasses `apps/api` entirely.
- **Qdrant has one enforcement layer** (payload filter, server-constructed) — Qdrant has no
  RLS-equivalent; this matches `06-security-model.md` §4's design as written. The filter is
  built entirely inside `packages/retrieval`, never accepts `workspace_id` from request
  input, and is unit-tested independent of any live Qdrant instance (assert the constructed
  `models.Filter` object's contents, not just its runtime effect).
  Its is_current_version and workspace_id must terms are unconditional.
- **`FORCE ROW LEVEL SECURITY` is required, not optional, given this deployment's
  configuration**: `packages/db/config.py` has a single `postgres_user` for all app
  connections, which — since migrations run as that same user — owns every table it creates.
  Postgres exempts table owners from RLS by default even when `ENABLE ROW LEVEL SECURITY` is
  set; only `FORCE ROW LEVEL SECURITY` closes that hole. This is called out explicitly
  because it is the easiest way to ship RLS that silently does nothing.
- **Fail-closed, not fail-open:** `current_setting('app.current_workspace_id', true)` (the
  `true` argument means "return NULL instead of erroring if unset") returns `NULL` when the
  GUC was never set (e.g. a code path that queries the DB without going through
  `require_workspace_role`); `NULL = anything` is `NULL` (falsy) in Postgres, so an unset GUC
  denies all rows rather than exposing all rows.
- **Audit logging is unchanged by this phase** (per spec Open Question 3's resolution below)
  — search queries are not written to `audit_log` here; that's Phase 7 territory.

## Rollout

Big-bang, no flag needed:
- The RLS migration is purely additive DDL and enforces exactly the same boundary the
  application layer already enforces correctly for every `apps/api` route (verified by the
  existing `011`/`012` test suite continuing to pass). It does change the outcome for code
  that writes to a protected table *without* going through `require_workspace_role` — the
  Celery worker and one raw-ORM integration test, both fixed above (Deviations found during
  implementation) — so "purely additive" held for the HTTP surface but not for background/
  direct-DB code paths; both categories are now accounted for.
- The search route is entirely new; nothing depends on it existing yet.
- Revert path: `alembic downgrade` drops the policies and `FORCE`/`ENABLE ROW LEVEL SECURITY`
  (down-migration provided); removing the router registration in `apps/api/main.py` removes
  the search endpoint. Both are independent and revertible without touching the other.

## Deviations found during implementation

- **The Celery worker never set the RLS scope.** `packages/ingestion/pipeline.py::run_ingestion`
  runs entirely outside `apps/api` — it reads `IngestionJob`/`DocumentVersion`/`Document` rows
  by `job_id` alone, in a separate process, with no HTTP request and no
  `require_workspace_role` call to set the GUC. Once migration `0002` was applied and tested
  against a live Postgres, this would have made the very first query in every ingestion job
  (`session.get(IngestionJob, job_id)`) return nothing, breaking `020`'s entire upload →
  ready flow — not caught by reading the code alone; only surfaced by tracing where each
  RLS-protected table is written outside `apps/api`. Fixed by threading `workspace_id`
  (already known and authorized at enqueue time, in `apps/api/routers/documents.py`) through
  `run_ingestion_job.delay(job_id, workspace_id)` -> `run_ingestion(..., workspace_id=...)`,
  which sets the GUC as its first action, before any query.
- **Transaction-local `set_config` doesn't survive `run_ingestion`'s multiple internal
  commits.** The async per-request helper (`set_workspace_scope`) correctly uses
  `is_local=true` because `apps/api` is one session/one transaction/one commit per request.
  `run_ingestion` commits repeatedly as a job advances through stages (queued → parsing →
  chunking → embedding → indexing → ready) — a transaction-local GUC would be discarded at
  the *first* of those commits. Added a session-scoped sync counterpart
  (`packages/db/rls.py::set_workspace_scope_sync`, `is_local=false`) instead; safe because
  `run_ingestion` always calls it first, so any stale value from a reused pooled connection is
  overwritten before any query runs.
- **`tests/integration/test_db_roundtrip.py` regressed.** It writes to `documents`/
  `document_versions` directly via the ORM without going through `apps/api`, so it hit the
  same class of gap as the worker. Fixed by having it call `set_workspace_scope` itself
  (`tests/integration/test_rls.py::_set_scope`) before writing, mirroring what a real request
  does — and updated its now-stale "no Row-Level Security" docstring.
- **API-key authentication was broken by RLS — found once Keycloak came online and the
  fuller integration suite could actually run.** `apps/api/deps/rbac.py::require_workspace_role`'s
  API-key branch called `resolve_active_api_key` (a `SELECT ... FROM api_keys WHERE key_hash
  = ...`, no `workspace_id` filter in the query itself — that check happened afterward in
  Python) *before* `set_workspace_scope`. Once `api_keys` became RLS-protected, that SELECT
  ran with no GUC set (or a stale one from a reused pooled connection), so it could never see
  the right row regardless of whether the key was valid — every API-key-authenticated request
  failed. This is the same chicken-and-egg class as the worker bug above, in a spot I missed
  the first time: unlike the JWT branch (whose first lookup, `workspace_members`, is
  deliberately RLS-exempt), the API-key branch's first lookup is against an RLS-protected
  table. Fixed by moving `set_workspace_scope(session, workspace_id)` before the
  `resolve_active_api_key` call, scoping to the *path's* `workspace_id` (client-claimed, not
  yet verified) — safe because setting the GUC only affects query visibility, not what's
  authorized; a key that doesn't exist or belongs elsewhere still resolves to `None` (RLS
  filters it out) exactly as before RLS existed. `tests/integration/test_audit_log.py` had
  the same "raw `db_session` never sets the GUC" issue as `test_db_roundtrip.py` for its
  direct `audit_log` read — fixed the same way. Caught by running
  `tests/integration/test_api_keys.py`/`test_audit_log.py` against live
  Postgres+Keycloak (22/22 integration tests green after the fix) — reinforces that the
  RLS audit needed a live auth flow, not just code reading, to find every
  queries-a-protected-table-before-the-GUC-exists gap.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `FORCE ROW LEVEL SECURITY` omitted or a policy misses `WITH CHECK`, silently leaving RLS a no-op for the app's own (owning) connection | Medium — easy to get subtly wrong | High — defeats the entire point of this phase | Dedicated test (`tests/integration/test_rls.py`) connects as the same app DB user, sets the GUC to workspace X, and asserts zero rows for workspace Y — run independent of `apps/api`, so it fails even if application code is never touched again |
| Join-based RLS policy on `document_versions`/`ingestion_jobs` (subquery per row) becomes a real cost once document/version counts grow | Low at current (assignment) scale | Low now, Medium later | Spec's own constraint says performance isn't a concern yet; if Phase 7 profiling flags it, revisit denormalizing `workspace_id` onto these tables (see Alternatives) |
| `SET LOCAL`/`set_config(..., true)` correctness depends on the one-session-per-request invariant in `apps/api/deps/db.py::get_db_session` | Low — that invariant is small and already load-bearing for transaction commit/rollback | High if ever violated (GUC could leak across requests on a pooled/reused session) | No code change proposed here; documented as an invariant this feature now additionally depends on, so a future change to session lifecycle must re-check it |
| `audit_log`'s RLS policy has no NULL-workspace branch, so a future system-level audit event (no workspace) would be silently rejected by `WITH CHECK` | Low — no current code path writes one | Low — would surface immediately as a write failure, not silent data loss | Documented here; not solved speculatively since nothing needs it yet |
| Adding `text` to the Qdrant payload increases point storage size | Low at current corpus sizes | Low | Accepted; revisit truncation/compression if Phase 6/7 profiling shows it matters |
| "Call `set_workspace_scope`/`_sync` first" is a convention every new call site must remember, not a structural guarantee — real implementation found it forgotten independently in the Celery worker, the API-key auth branch, and two raw-session tests (see Deviations) | Medium — a `/simplify` pass's altitude review flagged this as unaddressed after four independent instances | Medium — each instance so far has failed loud/closed (empty results or a cast error), never leaked data, but a future call site could get unlucky | Not fixed in this phase (would mean a session-factory redesign requiring `workspace_id` up front, or a SQLAlchemy `before_cursor_execute` hook asserting the GUC is set before touching a protected table — both are structural changes bigger than this spec's scope). Worth a small follow-up spec once a few more call sites exist to design against |

## Alternatives considered

- **Denormalize `workspace_id` onto `document_versions`/`ingestion_jobs`** (mirroring the old
  `tenant_id` denormalization pattern `02-data-model.md` §2 describes) instead of a
  join-based RLS policy — rejected for now: it reintroduces exactly the "must stay in sync on
  any re-parenting" burden that doc warns about, for a performance problem that doesn't exist
  yet at this scale (spec's own constraint). Revisit if Phase 7 shows it's a real bottleneck.
- **Application-layer filtering only, RLS deferred further** — rejected: `012` already
  deferred RLS *to* this phase, not past it; the roadmap frames Phase 4 as exactly where
  defense-in-depth lands before Phase 5 builds hybrid search on top.
- **Build the full hybrid (dense+sparse+RRF+rerank) pipeline now instead of a dense-only
  stub** — rejected: explicitly Phase 5's scope; doing it here blurs the phase boundary the
  roadmap deliberately drew and inflates this spec well past "RBAC filtering."
- **Route shape without a `workspace_id` path segment** (resolve workspace purely from an
  implicit "active workspace" concept) — rejected: inconsistent with every existing route's
  nesting (`/workspaces/{workspace_id}/documents`, `/jobs`, ...), and the "never
  client-editable" property doesn't actually require hiding the ID from the URL — it requires
  re-validating it server-side against membership, which `require_workspace_role` already
  does regardless of where the ID appears in the request.
