# Spec: Hybrid Retrieval + Reranking

- **ID:** `040-hybrid-retrieval-reranking`
- **Roadmap phase:** [08-roadmap.md](../architecture/08-roadmap.md) Phase 5 — Hybrid
  Retrieval + Reranking (`040-049`)
- **Status:** draft
- **Owner:** Saravanan Shanmugam
- **Date:** 2026-09-15

## Problem statement

`030-workspace-rbac-filtering` shipped the first real query path in this repo
(`packages/retrieval`, `POST /workspaces/{workspace_id}/search`) — deliberately dense-vector
only, by design (`030`'s own non-goals), so the mandatory workspace isolation filter could be
built and proven against a real search endpoint before hybrid search complexity landed on
top. `04-retrieval-design.md` §1 names the gap dense-only search leaves: no sparse/lexical
signal, so queries that hinge on an exact term — a contract clause number, a table header, a
proper noun, an acronym — are under-served, because dense embeddings weight semantic
similarity over rare exact tokens. This phase is where `04-retrieval-design.md`'s full target
pipeline (dense + sparse → RRF fusion → cross-encoder rerank) actually gets built.

This is not purely a read-path change. The Qdrant collection `packages/ingestion/qdrant_setup.py`
creates today has a single anonymous dense vector — no named sparse vector configured — and
`packages/ingestion/pipeline.py` only ever computes and upserts a dense embedding per chunk.
Adding a sparse leg to search requires a sparse vector to exist on every point in the first
place, which means this phase touches ingestion (write path) as well as retrieval (read
path), not `packages/retrieval` alone.

## Goals

- Add a sparse/lexical search leg alongside the existing dense leg, using Qdrant's native
  sparse vector support, computed via FastEmbed at ingestion time and stored as a named
  sparse vector on every point (`04-retrieval-design.md` §2-3).
- Fuse the dense and sparse ranked candidate lists with Reciprocal Rank Fusion (RRF) in
  `packages/retrieval`, producing one merged candidate set before reranking
  (`04-retrieval-design.md` §4's "why fuse-then-rerank" reasoning).
- Add a cross-encoder reranking stage that scores (query, chunk) pairs on the fused
  candidates and reorders them, with the final top-K (default 6-8) passed back from the
  search endpoint.
- The mandatory, server-constructed workspace filter
  (`packages/retrieval/filters.py::build_workspace_filter`, from `030`) applies unchanged to
  **both** the dense and sparse legs before fusion — hybrid search and reranking operate
  strictly within the caller's authorized set, exactly as `06-security-model.md` §4 already
  requires and `030`'s test suite already proves for the dense-only case. This phase does not
  touch, weaken, or re-litigate that filter.
- `packages/ingestion/pipeline.py` computes a sparse vector per chunk (same FastEmbed call
  site as the existing dense `embeddings.embed_documents` call) and includes it in the
  upserted point alongside the existing dense vector.
- The Qdrant collection gains the named sparse vector Qdrant requires
  (`packages/ingestion/qdrant_setup.py`) — existing points ingested before this phase do not
  need to be preserved (no production data exists yet, same norm `012`/`030` established);
  local dev/test re-ingests from fixtures.
- The existing `POST /workspaces/{workspace_id}/search` route (`030`) is extended, not
  replaced — same request shape, same mandatory-filter guarantee, same auth/RBAC guard;
  only the ranking behind it changes.
- `030`'s authorization test suite (`tests/integration/test_search_rbac.py`) continues to
  pass unmodified in intent: cross-workspace search still returns `403`/`404` with zero
  leakage, and in-workspace search still only ever returns chunks whose payload
  `workspace_id` matches — now proven against the hybrid pipeline, not just the dense one.

## Non-goals

- **Not** multimodal retrieval quality (vision captioning for images, table
  summary/schema/normalized-row intelligence) — that is Phase 6 (`050-059`,
  `05-multimodal-strategy.md`). This phase improves ranking quality of whatever text is
  already indexed; it does not change what text gets produced for images/tables.
- **Not** a golden evaluation dataset or recall/precision measurement — that is Phase 7
  (`060-069`, `07-evaluation-observability.md`). This phase can be built and reviewed without
  a formal before/after quality benchmark; `07`'s eval framework is explicitly where "with
  and without the reranker" gets measured per `04-retrieval-design.md` §4.
- **Not** a chat/generation endpoint — `POST /workspaces/{workspace_id}/search` still returns
  ranked chunks, not a synthesized answer. Generation is a later phase.
- **Not** any change to the workspace isolation model, the RLS policies, or the RBAC route
  guards `030` shipped — this phase is purely additive to the ranking pipeline behind an
  already-authorized, already-filtered query.
- **Not** finer-grained document ACLs, optional client-facing filters (`filename`,
  `content_type`, `page_range`), or any other retrieval knob `04-retrieval-design.md` §6
  mentions as future — only the ranking pipeline itself (sparse leg, fusion, rerank) is in
  scope.
- **Not** a production data migration for the Qdrant collection — existing local
  dev/test points are dropped/re-ingested, matching `012`'s established norm for this
  project's pre-launch state.

## User-facing behavior

No UI yet; observable behavior is at the API-consumer level, extending `030`'s contract.

- `POST /workspaces/{workspace_id}/search` accepts the same request shape as today
  (`query`, `k`). Behind the scenes, the response is now produced by dense+sparse+RRF+rerank
  instead of dense-only — same shape response (ranked chunks with scores), better ranking,
  especially for queries containing exact terms the corpus uses verbatim (clause numbers,
  proper nouns, table headers, acronyms).
- All existing `030` authorization guarantees hold: a caller who is not a member of the
  target workspace still gets `403`/`404` with zero leakage; a caller who is a member only
  ever sees chunks from documents in their own workspace, now verified against the richer
  pipeline.
- Newly ingested documents (post-deployment) get sparse vectors computed automatically as
  part of the existing async ingestion flow — no new user-facing step, no new upload
  parameter.

## Acceptance criteria

- [ ] Every newly-ingested chunk's Qdrant point carries a named sparse vector in addition to
      the existing dense vector.
- [ ] `packages/retrieval` exposes a sparse search function analogous to `dense_search`
      (`030`), using the same mandatory `build_workspace_filter` on the sparse leg exactly as
      the dense leg already does.
- [ ] An RRF fusion function combines a dense-ranked list and a sparse-ranked list into one
      merged candidate list, covered by a unit test with fixed input rankings and an
      expected fused order (no live services needed).
- [ ] A reranking function scores the fused candidates against the query and reorders them;
      covered by a unit test with a fake/mock reranker asserting the call shape and the
      reordering logic.
- [ ] `POST /workspaces/{workspace_id}/search` returns results produced by the full
      dense+sparse+RRF+rerank pipeline; an integration test demonstrates a lexical-heavy
      query (e.g. an exact phrase/number present in the fixture PDF) surfaces the correct
      chunk, exercising the sparse leg meaningfully rather than only the dense one.
- [ ] `tests/integration/test_search_rbac.py`'s authorization guarantees still pass
      unmodified against the new pipeline: cross-workspace search → `403`/`404`, zero
      leakage; in-workspace search → only that workspace's chunks, across all three stages
      (dense, sparse, fused/reranked).
- [ ] `uv run pytest tests/unit` passes with no live services.
- [ ] `uv run pytest tests/integration` passes against the real stack (Postgres, MinIO,
      Qdrant, Memurai, Keycloak, a running Celery worker, a real `OPENAI_API_KEY`, plus
      whatever the chosen reranker needs — self-hosted model weights or an API key).
- [ ] `04-retrieval-design.md` is updated to mark the sparse/fusion/rerank stages as
      implemented (currently described as target-only).

## Constraints

- Python 3.12, `uv`-managed. New code follows the `DocumentPortalException`-style error
  wrapping already established in `packages/retrieval` (`RetrievalError`).
- Must not regress any `030` acceptance criteria — the full existing integration suite
  (34 tests as of `030`) must still pass.
- The mandatory workspace filter contract (`build_workspace_filter`) is frozen — this spec
  extends what runs around it, never what it does.
- Local dev/test must stay runnable the way `030` verified it (native Postgres/Keycloak,
  Qdrant Cloud, natively-run MinIO, a `--pool=solo` Celery worker on Windows).
- Whatever reranker is chosen must not require infrastructure this project doesn't already
  have easy access to (no new paid service without an explicit decision — see Open
  questions).

## Open questions

1. **Sparse model: BM25 or SPLADE?** `04-retrieval-design.md` §2 names both as options via
   FastEmbed without picking one. BM25 is simpler, has no model weights to download, and is
   the more standard/interpretable lexical baseline; SPLADE is a learned sparse model that
   can capture some semantic-lexical overlap but adds a model-download/inference cost at
   ingest time. Leaning BM25 for simplicity given this phase's scope. → `plan.md`.
2. **Reranker: self-hosted cross-encoder or a hosted API (Cohere Rerank)?** Self-hosted
   (e.g. `BAAI/bge-reranker-large`) has no per-call cost and no external dependency but adds
   a model download and CPU/GPU inference cost to this dev environment; Cohere Rerank has no
   local compute cost but is a paid API needing a key and network call per search. Given this
   project's general preference for free-tier-friendly providers, leaning self-hosted unless
   local inference cost proves impractical on this dev machine. → `plan.md`.
3. **Collection schema change strategy.** Adding a named sparse vector to the existing Qdrant
   collection — recreate the collection (simplest, loses existing dev/test points, consistent
   with `012`'s "no production data to preserve" norm) vs. an in-place schema update if
   Qdrant supports adding a sparse vector config to an existing collection without recreation.
   → `plan.md`.
4. **Does the search response schema change?** `030`'s `SearchResultOut` returns one `score`
   per result. With fusion + reranking, is that the final reranker score only, or should the
   response also surface intermediate dense/sparse/fused scores for debugging/eval purposes
   (Phase 7 might want this)? Leaning: final score only for now, keep the response contract
   stable; revisit if Phase 7 needs more. → `plan.md`.
