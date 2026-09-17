# Tasks: Hybrid Retrieval + Reranking

- **Plan:** [plan.md](plan.md) (approved 2026-09-15)
- **Status:** done — 86/86 unit tests, 35/35 integration tests (full real stack: Postgres,
  MinIO, Qdrant Cloud, Memurai, Keycloak, a Celery worker, real `OPENAI_API_KEY`), including
  a new live test proving the sparse leg actually changes behavior (an exact rare
  alphanumeric ID surfaces correctly through the hybrid pipeline) and a clean re-run of
  `030`'s full authorization suite against the new pipeline. One real deviation from
  `plan.md` found and fixed during implementation: Qdrant's `update_collection` cannot add a
  new named sparse vector to an existing collection (confirmed against live Qdrant Cloud,
  not just the SDK's type signature) — `ensure_collection` recreates the collection instead;
  see `plan.md`'s Deviations section.

Work top to bottom. Each group should leave the system in a runnable state. Check items off
with `- [x]` as completed; do not delete or renumber finished items.

## Group 1 — Dependency + Qdrant sparse-vector schema

- [x] Add `fastembed>=0.5` to `pyproject.toml`, run `uv sync`. — files: `pyproject.toml` —
      verify: resolved to `fastembed==0.8.0`;
      `from fastembed import SparseTextEmbedding; from fastembed.rerank.cross_encoder import
      TextCrossEncoder` imports clean; confirmed `"Qdrant/bm25"` and
      `"Xenova/ms-marco-MiniLM-L-6-v2"` are real supported model names via
      `list_supported_models()` on both classes before committing to them in config.
- [x] Add `sparse_embedding_model: str = "Qdrant/bm25"` to both
      `packages/ingestion/config.py::Settings` and `packages/retrieval/config.py::Settings`
      (must match — see `plan.md`). — files: `packages/ingestion/config.py`,
      `packages/retrieval/config.py`, `tests/unit/test_ingestion_config.py` (new),
      `tests/unit/test_retrieval_config.py` (extended) — verify: 4 passed.
- [x] Add `reranker_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"` to
      `packages/retrieval/config.py::Settings` only. — files: `packages/retrieval/config.py`
      — verify: covered by the same 4-test run above.
- [x] Extend `packages/ingestion/qdrant_setup.py::ensure_collection` to idempotently ensure a
      named `"sparse"` vector exists. — files: `packages/ingestion/qdrant_setup.py`,
      `tests/unit/test_ingestion_qdrant_setup.py` (new) — verify: 3 passed. **Deviation from
      plan.md, found while implementing:** the plan called for adding the sparse vector to an
      existing collection via `update_collection(sparse_vectors_config=...)`; live Qdrant
      Cloud rejected this with `400 Bad Request: "Wrong input: Not existing vector name
      error: sparse"` — that parameter updates an already-configured sparse vector, it can't
      introduce a new one. Fixed: `ensure_collection` now deletes and recreates the
      collection (with both vector configs) when the sparse vector is missing. `plan.md`
      updated throughout (Summary, Component ownership, Data model changes, Rollout,
      Alternatives) plus a new Deviations section recording this.
- [x] Run `ensure_collection` against the live Qdrant Cloud collection from `030` and confirm
      the sparse vector is added. — files: none (verification only) — verify: ran directly
      against live Qdrant — before: `sparse_vectors=None`, 1158 points; after:
      `sparse_vectors={'sparse': SparseVectorParams(...)}`, 0 points (the collection was
      recreated, per the deviation above — `030`'s test points are gone, re-ingestion needed
      before Group 2's live verification and any further hybrid-search testing).

## Group 2 — Ingestion: compute and store sparse vectors

- [x] In `packages/ingestion/pipeline.py::run_ingestion`, compute a sparse vector per chunk
      via `SparseTextEmbedding` alongside the existing dense `embeddings.embed_documents`
      call, and include it in each point: `vector={"": dense_vector, "sparse":
      models.SparseVector(indices=..., values=...)}`. — files:
      `packages/ingestion/pipeline.py`, `workers/celery_app.py` (constructs the
      `SparseTextEmbedding` instance once at module scope alongside `_settings`, not per
      task — loading BM25's vocab/IDF stats has a real one-time cost).
      **Deviation from `plan.md`'s verify step:** skipped adding a new
      `test_ingestion_pipeline_sparse.py` unit test. `run_ingestion` has zero existing unit
      test coverage of any kind — checked before writing one — because it's only ever been
      tested against the real stack (parsing, storage, Qdrant, OpenAI are too much to
      meaningfully mock without inventing a large mock harness this codebase has never
      needed before; `tests/integration/conftest.py` states this project's explicit
      real-dependencies-over-mocks preference). Adding one mocked unit test just for the
      sparse vector would fight that established convention rather than follow it. Verified
      live instead — see next task. — verify: `uv run pytest tests/unit` — 70 passed, no
      regressions.
- [x] Re-run `test_upload_and_ingest.py` against the real stack and inspect an upserted
      point directly to confirm it carries both a dense vector (default) and a named
      `"sparse"` vector. — files: none (verification only) — verify:
      `uv run pytest tests/integration/test_upload_and_ingest.py` — 1 passed (Celery worker
      restarted first — it had loaded the pre-sparse-vector code at startup and doesn't
      hot-reload). Direct `scroll(..., with_vectors=True)` on a real point confirmed
      `vector.keys() == ['sparse', '']`, dense vector length 3072, sparse vector with real
      indices/values, and `text` payload intact.

## Group 3 — `packages/retrieval`: sparse search, fusion, rerank

- [x] Add `point_id: str` to `packages/retrieval/dense.py::SearchResult`, populated from
      `point.id`. — files: `packages/retrieval/dense.py` — verify: 4 passed (extended
      `tests/unit/test_retrieval_search.py`'s existing assertions and fixture).
      **Also, proactively (not in the original task list):** factored the point→
      `SearchResult` mapping loop out into `dense.py::map_points_to_results`, since writing
      `sparse.py` right after made the duplication obvious immediately rather than waiting
      for a later cleanup pass to find it.
- [x] Add `packages/retrieval/sparse.py::sparse_search(...)`, mirroring `dense_search`'s
      shape and error-wrapping (now sharing `map_points_to_results`), using
      `SparseTextEmbedding.query_embed()` and `qdrant_client.query_points(...,
      using="sparse", query_filter=build_workspace_filter(...))`. — files:
      `packages/retrieval/sparse.py` (new), `tests/unit/test_retrieval_sparse.py` (new) —
      verify: 4 passed, no live services.
- [x] Add `packages/retrieval/fusion.py::reciprocal_rank_fusion(dense_results,
      sparse_results, rrf_k=60) -> list[SearchResult]`. — files:
      `packages/retrieval/fusion.py` (new), `tests/unit/test_retrieval_fusion.py` (new) —
      verify: 5 passed — hand-computed RRF scores for a 4-point fixture matched the
      implementation exactly; also covers a point appearing in both lists outranking a
      rank-1-only point, dedup, empty-list handling, and that fusion doesn't touch `.score`
      (rerank does that).
- [x] Add `packages/retrieval/rerank.py::rerank(query, candidates, cross_encoder, top_k=8)
      -> list[SearchResult]` using `TextCrossEncoder`. — files: `packages/retrieval/rerank.py`
      (new), `tests/unit/test_retrieval_rerank.py` (new) — verify: 7 passed — reordering,
      `top_k` truncation, `.score` replaced with the reranker's score (not the fused score),
      `None` text handled without crashing, empty-candidates short-circuit, failure wrapping.

## Group 4 — Wire the orchestrator

- [x] Update `packages/retrieval/search.py::search()` to: pull `_CANDIDATE_POOL_SIZE=30`
      dense + 30 sparse candidates (each independently workspace-filtered) →
      `reciprocal_rank_fusion` → `rerank` down to the caller's `k`. Added module-cached
      (`lru_cache`) `SparseTextEmbedding`/`TextCrossEncoder` instances alongside the existing
      Qdrant/OpenAI-embeddings caching. — files: `packages/retrieval/search.py` — verify:
      `uv run python -c "from packages.retrieval.search import search"` imports clean; full
      `uv run pytest tests/unit` run below confirms no regressions at the lower layers.
- [x] `apps/api` route/schema contract confirmed frozen — `apps/api/schemas/search.py` is
      byte-identical to `030`; `apps/api/routers/search.py`'s only change is its own
      docstring, corrected from "Dense-vector-only search... hybrid/rerank land in Phase 5"
      (now stale — this *is* Phase 5) to describe the hybrid pipeline it now calls into.
      Request/response shapes, auth guard, and route path are all unchanged. — files:
      `apps/api/routers/search.py` (docstring only) — verify: manual diff against the file's
      content from earlier in this session — only the docstring differs.

## Group 5 — Live verification, docs, regression

- [x] Add an integration test demonstrating the sparse leg matters: a lexical-heavy query
      (an exact phrase/number from `tests/fixtures/sample.pdf`) surfaces the correct chunk.
      Used `"BLR-MSA-2026-019"`, a synthetic Contract ID on page 9 — a rare, semantically
      meaningless alphanumeric string exactly matching `04-retrieval-design.md` §1's stated
      dense-only weak spot. — files: `tests/integration/test_hybrid_search.py` (new) —
      verify: 1 passed against the real stack (cross-encoder weights downloaded on first
      use, ~15s one-time cost, then the full dense+sparse+RRF+rerank pipeline correctly
      surfaced the chunk containing the exact string).
- [x] Re-run `tests/integration/test_search_rbac.py` unmodified and confirm all 5 cases still
      pass against the new hybrid pipeline — the authorization regression gate `plan.md`
      names. — files: none — verify:
      `uv run pytest tests/integration/test_search_rbac.py` — 5 passed.
- [x] Update `04-retrieval-design.md` (§1-3: mark sparse/fusion/rerank implemented, note the
      BM25/MiniLM choices) and `02-data-model.md` §3 (note the named `sparse` vector) per
      `plan.md`'s Architecture doc deltas. — files: `specs/architecture/04-retrieval-design.md`,
      `specs/architecture/02-data-model.md`.
- [x] Full regression: `uv run pytest tests/unit` (no live services) and
      `uv run pytest tests/integration` (full live stack) both green. — verify: 86 passed
      (unit), 35 passed (integration, one combined run of the whole `tests/integration`
      directory).
- [x] `specs/README.md` gains a `040` row; status set to `done`.

## Verification (end of increment)

- [x] All `spec.md` acceptance criteria satisfied.
- [x] `uv run pytest tests/unit` passes with no live services — 86 passed.
- [x] `uv run pytest tests/integration` passes against the full real stack — 35 passed.
- [x] `04-retrieval-design.md`, `02-data-model.md` updated per `plan.md`'s Architecture doc
      deltas.
- [x] `specs/README.md` gains a `040` row; status set to `done`.
