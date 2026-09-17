# Plan: Hybrid Retrieval + Reranking

- **Spec:** [spec.md](spec.md) (approved 2026-09-15)
- **Status:** draft

## Summary

Add a sparse (BM25) leg alongside the existing dense leg, fuse the two with Reciprocal Rank
Fusion, and rerank the fused candidates with a self-hosted cross-encoder — all via a single
new dependency, `fastembed`, which provides both the BM25 sparse embedder and the
cross-encoder reranker (confirmed: `fastembed.sparse.SparseTextEmbedding` and
`fastembed.rerank.cross_encoder.TextCrossEncoder`). The mandatory workspace filter
(`packages/retrieval/filters.py::build_workspace_filter`) is applied unchanged to both the
dense and sparse legs, independently, before fusion — nothing about isolation changes. The
Qdrant collection gains a named sparse vector; `ensure_collection` recreates the collection
when it's missing, since Qdrant doesn't support adding one in-place to an existing collection
(see Deviations found during implementation — this was the plan's original assumption, and
implementation proved it wrong). Local dev/test data re-ingests cleanly; this is not treated
as a production migration this spec owns.

## Architecture doc deltas

| Doc | Change |
|---|---|
| `04-retrieval-design.md` | Mark the sparse/fusion/rerank stages (§2 pipeline, §3 stage table) as implemented; note the concrete choices made here (FastEmbed BM25, FastEmbed `TextCrossEncoder` with a MiniLM-class model rather than the doc's `BAAI/bge-reranker-large` example — see Alternatives) so the doc reflects what's actually running, not just the target shape. |
| `02-data-model.md` | §3 (Qdrant payload schema): note the collection now has a named `sparse` vector in addition to the existing unnamed dense vector; the payload schema itself (fields) is unchanged. |

## Component/module ownership

- **`pyproject.toml`** — add `fastembed>=0.5` (floor chosen because `TextCrossEncoder`
  support needs to be present; the exact resolved version is whatever `uv add fastembed`
  picks at implementation time).
- **`packages/ingestion/config.py`** and **`packages/retrieval/config.py`** — both gain
  `sparse_embedding_model: str = "Qdrant/bm25"`. Both packages need it (ingestion embeds
  chunks, retrieval embeds queries) and the two **must** agree, or the sparse vectors are
  incomparable — same reasoning `030` already applied to `openai_embedding_model` between
  these two packages.
- **`packages/retrieval/config.py`** only — gains `reranker_model: str =
  "Xenova/ms-marco-MiniLM-L-6-v2"` (read-path only; ingestion never reranks).
- **`packages/ingestion/qdrant_setup.py::ensure_collection`** — extended to also ensure the
  named sparse vector exists (idempotent: check `client.get_collection(...).config.params.sparse_vectors`
  for the name; if missing on an existing collection, delete and recreate it with both vector
  configs — see Deviations for why this is a recreate, not an `update_collection` patch),
  following the same idempotent-on-every-startup pattern already used for payload indexes.
- **`packages/ingestion/pipeline.py::run_ingestion`** — computes a sparse vector per chunk
  via `SparseTextEmbedding` alongside the existing dense `embeddings.embed_documents` call,
  and includes it in each point: `models.PointStruct(id=..., vector={"": dense_vector,
  "sparse": sparse_vector}, payload=...)` (Qdrant's convention for mixing an unnamed default
  vector with named ones — the empty string key addresses the existing unnamed dense vector).
- **`packages/retrieval/sparse.py`** (new) — `sparse_search(...)`, mirroring `dense.py`'s
  shape: embeds the query via `SparseTextEmbedding`, queries Qdrant with `using="sparse"`
  and the same `build_workspace_filter`, returns `list[SearchResult]`.
- **`packages/retrieval/dense.py`** — `SearchResult` gains a `point_id: str` field (the
  Qdrant point ID — deterministic per chunk, per `packages/ingestion/pipeline.py::_point_id`)
  so fusion has a stable join key across the two ranked lists. No other change; still usable
  standalone.
- **`packages/retrieval/fusion.py`** (new) — `reciprocal_rank_fusion(dense_results,
  sparse_results, rrf_k=60) -> list[SearchResult]`: merges by `point_id`, computes `Σ
  1/(rrf_k + rank)` per point across whichever list(s) it appears in, returns deduped results
  sorted by fused score descending. (Named `rrf_k` specifically to avoid colliding with the
  unrelated `k` = "how many final results" parameter used everywhere else in this package.)
- **`packages/retrieval/rerank.py`** (new) — `rerank(query, candidates, top_k=8) ->
  list[SearchResult]`: scores each candidate's `.text` against `query` via
  `TextCrossEncoder`, sorts descending, returns the top `top_k` with `.score` replaced by the
  reranker's score (per Open Question 4's resolution below).
- **`packages/retrieval/search.py::search()`** — becomes the orchestrator: `dense_search`
  and `sparse_search` each pull ~30 candidates (independently workspace-filtered) → `
  reciprocal_rank_fusion` → `rerank` down to the caller's requested `k`. Gains
  module-cached (`lru_cache`) `SparseTextEmbedding`/`TextCrossEncoder` instances, matching
  the client-caching pattern the `030` `/simplify` pass already established for the
  Qdrant/OpenAI clients in this same file.
- **`apps/api/routers/search.py`, `apps/api/schemas/search.py`** — unchanged. Same request/
  response contract; only what runs behind `packages.retrieval.search` changes.

## Data model changes

- **Qdrant collection**: gains a named sparse vector (`"sparse"`). Realized via a recreate
  (delete + create with both vector configs), not an in-place `update_collection` — see
  Deviations for why. This drops `030`'s existing test points entirely, not just their
  sparse vector; local dev/test re-ingests from fixtures. No backfill job is in scope.
- **No Postgres changes.**
- **`pyproject.toml`**: `fastembed` added.

## API contract

No changes. `POST /workspaces/{workspace_id}/search` keeps `030`'s exact request
(`{"query": str, "k": int}`) and response (`{"results": [...]}`) shapes. `SearchResultOut`'s
`score` field now reflects the reranker's score rather than a raw cosine similarity — this is
an internal ranking-quality change, not a contract change (the field's meaning was never
specified as "cosine similarity" in `030`'s contract, only as an ordering signal).

## Retrieval / ingestion impact

- **Ingestion**: one additional embedding computation per chunk (BM25 sparse — a statistical
  term-frequency method, not a neural forward pass, so cheap and fast; no GPU, no meaningful
  latency add to a job that already tolerates multi-minute real-world runs on this dev box).
- **Retrieval**: the search request now does one dense query + one sparse query (both
  workspace-filtered, run against the same collection) instead of one; a pure-Python RRF
  fuse over ~60 combined candidates (negligible cost); and a cross-encoder forward pass over
  ~30 fused candidates for reranking — the one genuinely new latency cost on this path. Using
  a small MiniLM-class cross-encoder (see Alternatives) rather than a larger model keeps this
  in the sub-second range on CPU for a candidate pool this size, though it is not benchmarked
  here — Phase 7 (`060-069`) is where retrieval latency gets formally measured.
- Expected quality effect: better recall on exact-term queries per `04-retrieval-design.md`
  §1's stated gap; not measured quantitatively in this phase (spec's own non-goal — that's
  Phase 7's job).

## Security / tenancy impact

Extends `030`'s design without renegotiating it:

- `build_workspace_filter(workspace_id)` — unchanged — is passed to **both** `dense_search`
  and the new `sparse_search`, independently, before fusion. Neither leg is exempt; RRF and
  reranking only ever operate on candidates both legs were already only allowed to return.
- No new client-facing parameter can influence which workspace is queried — `search()`'s
  signature is unchanged (`workspace_id` still comes from the caller, resolved by
  `require_workspace_role`, never from the request body).
- `tests/integration/test_search_rbac.py` (from `030`) is the regression gate: it must keep
  passing unmodified in intent — cross-workspace search still `403`/`404` with zero leakage,
  in-workspace search still scoped — now exercised against the full hybrid pipeline instead
  of dense-only.

## Rollout

Big-bang, no flag:
- The Qdrant schema change (`ensure_collection` recreating the collection when the sparse
  vector is missing) is idempotent and self-healing on every worker/API startup, but is a
  one-time, real cutover in a shared environment — it drops whatever points existed under
  the old (dense-only) schema the moment any process first calls `ensure_collection` after
  this deploys. Acceptable pre-launch (no production data); would need an actual reindex
  strategy before this project has real user data to lose.
- The new dependency (`fastembed`) and its model downloads (BM25 has no model file — it's
  computed directly from token statistics; the cross-encoder does download weights on first
  use) are a one-time cold-start cost per environment, not a recurring one.
- No fallback path if the reranker is unavailable (e.g. model download fails) — a search
  request fails loudly with `RetrievalError` rather than silently degrading to
  fusion-only-no-rerank results. Consistent with this project's established preference for
  failing visibly over failing open/quiet (the same reasoning behind RLS's fail-closed
  design in `030`).
- Revert path: remove the sparse/fusion/rerank call chain from `search()`, falling back to
  `030`'s `dense_search`-only orchestration; the Qdrant sparse vector config can stay
  (harmless if unused) rather than needing a down-migration.

## Deviations found during implementation

- **`update_collection` cannot add a new named sparse vector to an existing collection —
  confirmed against live Qdrant Cloud, not just the client SDK's type signature.** This
  plan's Data model changes section originally called for an in-place addition via
  `update_collection(sparse_vectors_config=...)`, reasoning from the fact that
  `QdrantClient.update_collection`'s Python signature accepts that parameter. Running it for
  real against the `030`-era collection returned `400 Bad Request: "Wrong input: Not existing
  vector name error: sparse"` — the parameter exists for *updating* an already-configured
  sparse vector's index settings, not for introducing a brand-new one after creation. Fixed:
  `packages/ingestion/qdrant_setup.py::ensure_collection` now deletes and recreates the
  collection (with both vector configs from the start) whenever the sparse vector is missing,
  instead of patching in place. This is still safe under this project's established norm (no
  production data exists to preserve — `012`, `030`) but it did drop the 1,158 points `030`'s
  testing had accumulated in the shared Qdrant Cloud collection; re-ingestion is required
  before Group 2's live verification and going forward for any hybrid-search testing.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Cross-encoder CPU inference makes search noticeably slower than `030`'s dense-only baseline | Medium | Medium — not a correctness issue, but a UX one if search starts feeling slow | Chose a small MiniLM-class reranker over the spec's heavier example model specifically for this; formal latency measurement is Phase 7's job, not blocking this phase |
| Adding the sparse vector required recreating the Qdrant collection (see Deviations) — every pre-existing point, not just its sparse vector, is gone | Realized, not hypothetical — happened during Group 1 implementation | Low at current (assignment) scale — no real production corpus yet, `020`/`030` never claimed to preserve local test data across schema changes | Documented in Deviations; local dev/test fixtures re-ingest cleanly (same norm `012` established) |
| `fastembed`'s BM25/cross-encoder model artifacts add first-run download time/disk usage in any new environment (CI, a fresh dev machine) | Medium | Low — one-time cost, not recurring | Documented here; no caching/pre-fetch strategy built yet since this project has no CI pipeline exercising this today |
| RRF's `rrf_k=60` and the ~30-candidate pool size per leg are unvalidated heuristics, not tuned against this corpus | Medium | Low — these are the field's standard defaults (the original RRF paper and Qdrant's own examples both use k=60), just not proven optimal here | Accepted per spec's own non-goal; Phase 7's eval framework is explicitly where "with vs. without" gets measured |

## Alternatives considered

- **Cohere Rerank API instead of a self-hosted cross-encoder** — rejected: adds a paid
  external dependency and a per-search network round trip for a project that has otherwise
  stayed free/local-first at every prior infrastructure decision (Qdrant Cloud's free tier,
  self-hosted Keycloak, native Postgres/MinIO). `fastembed`'s `TextCrossEncoder` gets the
  same architectural slot (cross-encoder rerank on fused candidates) with zero added cost or
  external call.
- **SPLADE instead of BM25 for the sparse leg** — rejected for now: SPLADE is a learned
  sparse model requiring a neural forward pass at both index and query time; BM25 is a
  zero-training statistical method that directly targets the stated problem (exact-term
  matching: clause numbers, proper nouns, table headers) without the added model-inference
  cost. Revisit if Phase 7 eval shows BM25's ranking is insufficient.
- **`BAAI/bge-reranker-large`** (the spec's own example model) **instead of a MiniLM-class
  cross-encoder** — rejected: `bge-reranker-large` is a much larger model; on this project's
  CPU-only Windows dev box, a smaller model (`Xenova/ms-marco-MiniLM-L-6-v2`, `fastembed`'s
  common default) keeps rerank latency practical for local dev/testing without a GPU. Revisit
  if Phase 7 quality measurement shows the smaller model underperforms.
- **In-place `update_collection` instead of recreating the Qdrant collection** — attempted
  first (this section originally rejected recreation in favor of it), but reality disagreed:
  live Qdrant Cloud rejects `update_collection(sparse_vectors_config=...)` for a vector name
  that wasn't part of the original collection creation (see Deviations). Recreation is what's
  actually implemented in `ensure_collection`.
