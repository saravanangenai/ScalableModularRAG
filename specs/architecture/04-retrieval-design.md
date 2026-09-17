# Retrieval Design — Hybrid Search, Fusion, Reranking

- **Status:** approved baseline

> ⚠️ **Single-tenant as-built ([`specs/012`](../012-single-tenant-simplification/spec.md)).**
> The mandatory filter is `workspace_id` + ACL only — no `tenant_id` term. Multi-tenancy is
> the deferred target (roadmap Phase 10).
>
> **The full pipeline below is implemented** — dense search
> ([`specs/030-workspace-rbac-filtering`](../030-workspace-rbac-filtering/spec.md)) plus
> sparse search, RRF fusion, and reranking
> ([`specs/040-hybrid-retrieval-reranking`](../040-hybrid-retrieval-reranking/spec.md)).
> Concrete choices §2's "BM25/SPLADE" and "BAAI/bge-reranker-large, self-hosted, or Cohere
> Rerank API" left open: **BM25** via `fastembed.SparseTextEmbedding` (`Qdrant/bm25`,
> zero-training statistical method, no learned model), and a **self-hosted** FastEmbed
> `TextCrossEncoder` (`Xenova/ms-marco-MiniLM-L-6-v2` — chosen smaller than
> `bge-reranker-large` for practical CPU-only local inference), not Cohere.
> `packages/retrieval/filters.py::build_workspace_filter` is the mandatory filter §6
> describes; both the dense and sparse legs apply it independently, unchanged.

## 1. Current behavior (V1, to be replaced)

`src/retriever.py::MultimodalQdrantRetriever` does dense-only search
(`RetrievalMode.DENSE`, OpenAI `text-embedding-3-large`) with optional Qdrant payload
filters (`filename`, `document_id`, `content_types`, `page_number`/`page_from`/`page_to`).
There is no sparse/lexical signal, no fusion, and no reranking — `retrieve_with_scores`
returns raw cosine-similarity top-K straight from Qdrant. This is adequate for a demo but
weak on exact-term queries (contract clause numbers, table headers, proper nouns) where
lexical match matters more than semantic similarity.

## 2. Target pipeline (implemented — `packages/retrieval`)

```
query
  |
  +--> dense search (Qdrant, unnamed default dense vector, top N=30 — dense.py)
  |
  +--> sparse search (Qdrant named "sparse" vector, BM25 via fastembed.SparseTextEmbedding
  |     "Qdrant/bm25", top N=30 — sparse.py)
  |
  v
Reciprocal Rank Fusion (RRF, rrf_k=60) over the two ranked lists -> fused, deduped by point
  id (fusion.py)
  |
  v
Cross-encoder reranker (fastembed.rerank.cross_encoder.TextCrossEncoder,
"Xenova/ms-marco-MiniLM-L-6-v2", self-hosted) scores (query, chunk) pairs -> reorder,
truncate to k (rerank.py)
  |
  v
Top-K (default 8, caller-adjustable 1-50) returned by POST /workspaces/{workspace_id}/search
```

Every stage still applies the **mandatory tenant/workspace/ACL filter** from
`06-security-model.md` — hybrid search and reranking operate *within* the authorized set,
never around it.

## 3. Where each stage runs and what it solves

| Stage | Runs in | Solves |
|---|---|---|
| Dense search | Qdrant (existing collection, existing dense vector) | Semantic/paraphrase matches — "what does the incident policy say" matches text that never uses those exact words. This is what V1 already does. |
| Sparse search | Qdrant (named `"sparse"` vector on the same collection/point as the dense vector — `packages/ingestion/qdrant_setup.py`, `packages/retrieval/sparse.py`) | Exact lexical/keyword matches — clause numbers, proper nouns, table headers, acronyms — where dense embeddings under-weight rare exact tokens. Verified against a real query (`tests/integration/test_hybrid_search.py`): a rare alphanumeric ID surfaces correctly through the full pipeline. |
| RRF fusion | `packages/retrieval/fusion.py` (application code, not Qdrant) | Combines two rankings without needing to calibrate dense/sparse score scales against each other — rank-based fusion is scale-invariant, which raw score-averaging is not. |
| Cross-encoder rerank | `packages/retrieval/rerank.py`, self-hosted FastEmbed `TextCrossEncoder` | Both dense and sparse are bi-encoder-style approximations (query and document embedded independently); a cross-encoder that reads (query, chunk) jointly is much more accurate at judging true relevance, but too slow to run over the whole collection — so it only reranks the ~30 fused candidates, not all chunks. |
| Metadata filtering | Qdrant, applied to both dense and sparse legs before fusion | Tenant/workspace/ACL isolation (mandatory) plus optional user-facing filters (filename, content_type, page range) — same filters `build_filter` already supports, extended with tenant/workspace/ACL terms. |
| Top-K selection | `packages/retrieval` | Bounds what's sent to the LLM (cost, latency, context-window budget) — same role `max_context_chars`/`k` play in `src/generation.py` today. |

## 4. Why fuse-then-rerank instead of rerank-only or fusion-only

- Reranking the full candidate pool without first fusing dense+sparse would mean running two
  separate rerank passes or picking one retrieval mode arbitrarily — RRF gives one merged,
  diversity-aware candidate set at negligible cost before the comparatively expensive
  reranker runs.
- Fusion alone (no reranker) is what most "hybrid search" demos stop at, but RRF is still a
  cheap heuristic; a cross-encoder rerank is included as baseline on the theory that it
  moves recall@k/precision@k in practice.
- **Measured** (`060-retrieval-evaluation`, `eval/reports/20260916T135648Z-fbeccea.json` vs.
  `eval/reports/20260916T135709Z-fbeccea.json`, 7-case golden dataset, k=8): both
  dense-only and full hybrid+rerank hit recall@8 = 1.0. Dense-only actually scored a
  *higher* mean reciprocal rank (0.929 vs. 0.616) and ran ~6x faster (p50 360ms vs. 2172ms).
  This is a small (7-case) dataset and not proof the reranker is unnecessary in general, but
  it's evidence against assuming the reranker is free value — see
  `specs/060-retrieval-evaluation/tasks.md` for the full numbers. Worth growing the golden
  dataset and re-measuring before deciding whether reranking should stay on by default.

## 5. Content-type-aware retrieval

Tables and images are stored as distinct `content_type` values today
(`src/parsing.py::create_langchain_documents`) and that continues — but their *embedded
text* changes (see `05-multimodal-strategy.md`): tables get a generated summary in addition
to markdown, and images get a vision caption instead of relying on OCR alone. This directly
improves both the dense and sparse legs above, since better source text improves both.

## 6. API-level knobs (extends `src/retriever.py`'s existing filter kwargs)

Retrieval Service exposes the same shape of filter parameters the current retriever already
has (`filename`, `document_id`, `content_types`, `page_number`, `page_from`/`page_to`) plus
new ones: `workspace_id` (implicit from auth, not client-settable), `use_hybrid` (default
true), `rerank_top_n` (candidates sent to reranker), `k` (final top-K). This keeps the
existing `retrieve_with_scores` call shape recognizable to anything already built against it.

## 7. Related docs

- `05-multimodal-strategy.md` — what text gets embedded for images/tables
- `06-security-model.md` — how the mandatory filter is constructed and injected
- `07-evaluation-observability.md` — how retrieval quality (recall/precision) is measured
  before/after this pipeline change
