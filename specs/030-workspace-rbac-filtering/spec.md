# Spec: Workspace RBAC Filtering

- **ID:** `030-workspace-rbac-filtering`
- **Roadmap phase:** [08-roadmap.md](../architecture/08-roadmap.md) Phase 4 — Workspace/RBAC
  Filtering (`030-039`)
- **Status:** draft
- **Owner:** Saravanan Shanmugam
- **Date:** 2026-09-14

## Problem statement

`011-auth-and-workspaces` and `012-single-tenant-simplification` already gave every
workspace-scoped API route (`documents`, `jobs`, `api_keys`, `workspaces`) an
application-layer RBAC guard (`apps/api/deps/rbac.py::require_workspace_role`), resolved
from `workspace_members` and never trusted from client input. That part of
`06-security-model.md` §3 is largely in place.

Two things it does not cover, both explicitly deferred to this phase:

1. **No defense-in-depth.** `012` removed the tenant-scoped Postgres Row-Level Security
   policies along with the tenant layer and left workspace isolation as an
   application-layer-only boundary (`02-data-model.md` §0, `06-security-model.md` §5). A bug
   in a single query anywhere in `apps/api` — a missing `WHERE workspace_id = ...`, a
   forgotten `require_workspace_role` dependency on a new route — is currently the only thing
   standing between one workspace's rows and another's, with no second layer to catch it.
2. **No retrieval-time filter exists because no retrieval query path exists yet.**
   `packages/retrieval` is empty scaffolding (`.gitkeep` only) and `apps/api` has no
   search/chat/query router. `06-security-model.md` §4 and `04-retrieval-design.md` describe
   a mandatory, server-constructed `workspace_id` filter applied to Qdrant search — but
   there is currently no Qdrant search code path in this repo to apply it to.
   `020-async-ingestion-pipeline` writes `workspace_id` into every Qdrant point payload and
   `packages/ingestion/qdrant_setup.py` already creates a `workspace_id` payload index for
   this purpose, but nothing reads it back yet.

Per `08-roadmap.md`, Phase 5 (`040-049`, hybrid dense+sparse+RRF+rerank) is built on top of
whatever query path this phase establishes — deliberately, so hybrid search is built and
tested against an already-isolated system rather than having isolation bolted on after the
fact. That means this phase must produce a real, queryable search endpoint with the
mandatory filter wired in from the start, even though it stays deliberately simple
(single dense vector, no fusion, no reranking) — those upgrades are Phase 5's job, not
this one's.

## Goals

- Add workspace-scoped Postgres Row-Level Security as defense-in-depth behind the existing
  application-layer `workspace_id` filtering, per `06-security-model.md` §5 and the decision
  `012` deferred here. Policies key off a per-request session GUC set by the API after the
  caller's workspace access is resolved (the same shape `011` used for
  `app.current_tenant_id`, now `app.current_workspace_id`, scoped to workspace-owned tables
  only — no tenant tables exist to protect).
- Stand up the first real query path in `packages/retrieval` and a
  `POST /workspaces/{workspace_id}/search` (or equivalent) route in `apps/api`: dense-vector
  Qdrant search only (no sparse leg, no RRF, no cross-encoder reranker — that's Phase 5),
  reusing the existing dense embedding call pattern from the current prototype
  (`src/retriever.py` in the sibling repo) as reference, not by importing from it.
- The `workspace_id` term in that search's Qdrant filter is resolved server-side from the
  caller's authenticated `WorkspaceAccess` (already established by `require_workspace_role`)
  and is never accepted as a client-editable filter value. A request that cannot resolve a
  workspace is rejected before any Qdrant call is made — never defaulted to searching
  everything.
- Audit every existing workspace-scoped route (`documents`, `jobs`, `api_keys`, `workspaces`)
  against `06-security-model.md` §3-§5 and close any gap found (missing guard, a route that
  returns a distinguishable 404-vs-403, an unfiltered list query) — treat this as a
  verification pass over `011`/`012`'s RBAC work, not a rebuild of it.
- An authorization test suite (extending `tests/integration/test_document_routes_rbac.py`'s
  pattern) that specifically exercises retrieval: user A, authenticated and a member of
  workspace X, queries workspace Y (which A does not belong to) and gets `403`/`404` — never
  a `200` with zero or filtered results. A second case: a query correctly scoped to a
  workspace A belongs to only ever returns chunks whose payload `workspace_id` matches.
- `audit_log` gains a row for search queries at least at a coarse level (query text is
  reasonable to log per `06-security-model.md` §7's "chat queries, configurable" note) — or a
  documented decision not to, if query-volume logging is deferred. Resolve in `plan.md`.

## Non-goals

- **Not** hybrid search, RRF fusion, or cross-encoder reranking — that is Phase 5
  (`040-049`, `04-retrieval-design.md`). This phase's search endpoint is dense-only and is
  expected to be extended, not replaced, by Phase 5.
- **Not** a chat/generation endpoint — no LLM call, no answer synthesis, no citations
  assembly. This phase returns ranked chunks, not an answer. Generation is a later phase.
- **Not** document-level ACLs finer than workspace membership (e.g. per-document sharing) —
  `06-security-model.md` §4 mentions "any finer-grained document ACL" as a possible future
  dimension; this phase only implements the workspace dimension, which is all the current
  data model (`02-data-model.md` §0) supports.
- **Not** restoring tenant-level RLS or any tenant concept — `012` removed it; this phase
  works entirely within the single-tenant, workspace-only model.
- **Not** a rewrite of `require_workspace_role` or the existing RBAC dependency shape unless
  the audit (Goals, bullet 4) finds an actual defect. Preserve the existing pattern if it's
  sound.
- **Not** `apps/UI` or any frontend — this phase is API-only, consistent with every prior
  phase in this repo.

## User-facing behavior

No UI yet; observable behavior is at the API-consumer level.

- An authenticated member of workspace X can `POST /workspaces/X/search` with a query string
  and get back a ranked list of chunks (text/table/image metadata, page number, score) drawn
  only from documents ingested into workspace X.
- The same call against workspace Y, where the caller is not a member, returns `403` (or
  `404` if indistinguishable-from-nonexistent per `06-security-model.md` §5) — never a `200`
  with an empty or filtered list, and never any indication of whether workspace Y exists.
- A search request that omits a workspace (calls a route with no workspace segment/scope) is
  rejected at the routing/validation layer — there is no "search everything" mode.
- Even if an application-layer bug in some future route change forgets to filter by
  workspace, Postgres RLS independently blocks cross-workspace rows for any Postgres-backed
  resource (documents, jobs, conversations once they exist, etc.) — this is verified by a
  test that queries as workspace X's role but with a deliberately wrong/omitted
  application-layer filter and confirms zero rows come back, not just that the app-layer
  filter would have caught it.

## Acceptance criteria

- [ ] Every workspace-owned Postgres table (`documents`, `document_versions`,
      `ingestion_jobs`, `api_keys`, `audit_log`, and any table added since) has a
      Row-Level Security policy keyed on a session-scoped workspace GUC; the policy is
      proven to reject a session where the GUC is unset or set to a different
      `workspace_id`.
- [ ] `apps/api` sets the workspace GUC for the duration of each request's DB session,
      immediately after `require_workspace_role` resolves the caller's `workspace_id`, for
      every route currently using that dependency.
- [ ] A new `packages/retrieval` module exposes a dense-vector search function that takes a
      resolved `workspace_id` and constructs the Qdrant filter server-side — the caller
      cannot pass a `workspace_id` (or any other tenant/workspace-shaped field) through the
      request body/query params to override it.
- [ ] `POST /workspaces/{workspace_id}/search` (exact route name decided in `plan.md`)
      requires `viewer`+ role, returns ranked chunks scoped to that workspace, and rejects
      (`401`/`403`) exactly the same way the existing document/job routes do for
      unauthenticated/unauthorized callers.
- [ ] An authorization test proves: workspace A member queries workspace B → `403`/`404`,
      zero rows, zero leaked identifiers in the response body.
- [ ] An authorization test proves: workspace A member's query only ever returns chunks
      with payload `workspace_id == A`, using a fixture that has ingested documents into two
      distinct workspaces.
- [ ] The RLS audit above is repeated at the Postgres level directly (not just through the
      API) — a raw query executed with the workspace GUC set to X cannot read rows scoped to
      Y, independent of any application code.
- [ ] Existing route audit: every route in `apps/api/routers/{documents,jobs,api_keys,
      workspaces}.py` is checked against `06-security-model.md` §3-§5 and either confirmed
      compliant or fixed; the plan.md/tasks.md record which.
- [ ] `uv run pytest tests/unit` passes with no live services; the `020`/`012` integration
      suites (`test_upload_and_ingest`, `test_versioning`, `test_ingestion_failure`,
      `test_document_routes_rbac`, `test_api_keys`, `test_audit_log`, `test_auth_flow`,
      `test_jit_provisioning`) still pass against real Postgres/MinIO/Qdrant/Memurai/Keycloak.
- [ ] `02-data-model.md` and `06-security-model.md` are updated to reflect that
      workspace-scoped RLS and the retrieval-time filter are now implemented, not deferred
      (their ⚠️ DEFERRED markers for these specific items are removed or narrowed).
      `specs/README.md` gains a `030` row.

## Constraints

- Python 3.12, `uv`-managed. `packages/retrieval` follows the same
  `DocumentPortalException`-style error wrapping as `packages/ingestion`/`packages/auth`
  (`packages/exceptions`).
- Must not regress any existing `011`/`012`/`020` acceptance criteria — the full existing
  integration suite must still pass unmodified in behavior (test files may gain new cases,
  not lose coverage).
- RLS policies must not depend on the removed `app.current_tenant_id` GUC or any tenant
  table — single-tenant model only, per `012`.
- The search endpoint must not hold or forward provider API keys to any client — embedding
  calls stay server-side in `packages/retrieval`, consistent with `06-security-model.md` §6.
- Local dev/test must stay runnable the way `020`/`012` verified it (native Postgres/MinIO/
  Qdrant/Memurai/Keycloak, no Docker requirement).
- Performance/cost is not a concern yet (no caching, no batching requirements) — this phase
  optimizes for correctness of the isolation boundary, not latency; Phase 5 and Phase 7
  (evaluation/observability) are where retrieval quality and performance get tuned/measured.

## Open questions

1. **Search route shape.** Is `POST /workspaces/{workspace_id}/search` (matching the
   existing `/workspaces/{workspace_id}/documents` nesting style) the right shape, or should
   it live outside the workspace path segment with `workspace_id` resolved purely from
   membership (no path param at all, to make the "never client-editable" property even more
   structurally obvious)? → `plan.md`.
2. **RLS GUC granularity.** `011`'s removed tenant GUC was set once per request. Should the
   new workspace GUC be set the same way (once, right after `require_workspace_role`
   resolves), or does any route legitimately need to touch multiple workspaces in one
   request (e.g. `list_my_workspaces`) in a way that complicates a single-GUC-per-session
   model? → `plan.md`.
3. **Search audit logging.** Log every search query to `audit_log` (high volume, per
   `06-security-model.md` §7's "configurable, since it's high-volume" note) now, or defer
   query-level audit logging to Phase 7 (evaluation/observability) and only log
   workspace-membership/RBAC changes here as `011`/`012` already do? Leaning: defer to
   Phase 7, keep this spec's audit surface unchanged. → confirm in `plan.md`.
4. **Embedding model/provider for the dense leg.** `010`/`011`/`020` never wired an
   embedding provider into any package — `packages/retrieval` needs one to embed the query.
   OpenAI `text-embedding-3-large` (matching the sibling prototype and
   `04-retrieval-design.md` §1) is the obvious default; confirm no other provider is
   preferred before `plan.md` locks it in.
