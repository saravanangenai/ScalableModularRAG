# Retrieval Design — Hybrid Search, Fusion, Reranking

- **Status:** approved baseline

## 1. Current behavior (V1, to be replaced)

`src/retriever.py::MultimodalQdrantRetriever` does dense-only search
(`RetrievalMode.DENSE`, OpenAI `text-embedding-3-large`) with optional Qdrant payload
filters (`filename`, `document_id`, `content_types`, `page_number`/`page_from`/`page_to`).
There is no sparse/lexical signal, no fusion, and no reranking — `retrieve_with_scores`
returns raw cosine-similarity top-K straight from Qdrant. This is adequate for a demo but
weak on exact-term queries (contract clause numbers, table headers, proper nouns) where
lexical match matters more than semantic similarity.

## 2. Target pipeline

```
query
  |
  +--> dense search (Qdrant, existing dense vector, top N=~30)
  |
  +--> sparse search (Qdrant named sparse vector, BM25/SPLADE via FastEmbed, top N=~30)
  |
  v
Reciprocal Rank Fusion (RRF) over the two ranked lists -> fused top ~30
  |
  v
Cross-encoder reranker (BAAI/bge-reranker-large, self-hosted, or Cohere Rerank API) scores
(query, chunk) pairs -> reorder
  |
  v
Top-K (default 6-8) passed to Generation Service as context
```

Every stage still applies the **mandatory tenant/workspace/ACL filter** from
`06-security-model.md` — hybrid search and reranking operate *within* the authorized set,
never around it.

## 3. Where each stage runs and what it solves

| Stage | Runs in | Solves |
|---|---|---|
| Dense search | Qdrant (existing collection, existing dense vector) | Semantic/paraphrase matches — "what does the incident policy say" matches text that never uses those exact words. This is what V1 already does. |
| Sparse search | Qdrant (new named sparse vector on the same collection, using Qdrant's native sparse vector support with FastEmbed's BM25/SPLADE) | Exact lexical/keyword matches — clause numbers, proper nouns, table headers, acronyms — where dense embeddings under-weight rare exact tokens. This is the biggest single quality gap in V1. |
| RRF fusion | `packages/retrieval` (application code, not Qdrant) | Combines two rankings without needing to calibrate dense/sparse score scales against each other — rank-based fusion is scale-invariant, which raw score-averaging is not. |
| Cross-encoder rerank | `packages/retrieval`, calling a reranker model/API | Both dense and sparse are bi-encoder-style approximations (query and document embedded independently); a cross-encoder that reads (query, chunk) jointly is much more accurate at judging true relevance, but too slow to run over the whole collection — so it only reranks the ~30 fused candidates, not all chunks. |
| Metadata filtering | Qdrant, applied to both dense and sparse legs before fusion | Tenant/workspace/ACL isolation (mandatory) plus optional user-facing filters (filename, content_type, page range) — same filters `build_filter` already supports, extended with tenant/workspace/ACL terms. |
| Top-K selection | `packages/retrieval` | Bounds what's sent to the LLM (cost, latency, context-window budget) — same role `max_context_chars`/`k` play in `src/generation.py` today. |

## 4. Why fuse-then-rerank instead of rerank-only or fusion-only

- Reranking the full candidate pool without first fusing dense+sparse would mean running two
  separate rerank passes or picking one retrieval mode arbitrarily — RRF gives one merged,
  diversity-aware candidate set at negligible cost before the comparatively expensive
  reranker runs.
- Fusion alone (no reranker) is what most "hybrid search" demos stop at, but RRF is still a
  cheap heuristic; a cross-encoder rerank is what actually moves recall@k/precision@k in
  practice, so it's included as baseline, not a stretch goal — the evaluation framework in
  `07-evaluation-observability.md` should be able to measure this pipeline with and without
  the reranker to confirm it's earning its latency cost.

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
