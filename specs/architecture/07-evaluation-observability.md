# Evaluation & Observability Plan

- **Status:** approved baseline

## 1. Current state (V1)

`logger/custom_logger.py` (structlog) writes structured logs to `logs/*.log` and each
`src/*` module logs lifecycle events (`ingestion_initialized`, `documents_retrieved`,
`generation_completed`, etc.) with useful fields (query, k, result_count, model_name,
usage). This is a good foundation — it just isn't aggregated, traced end-to-end, sampled
into dashboards, or connected to any repeatable quality measurement. There is no eval
dataset and no automated way to tell if a prompt/chunking/retrieval change made answers
better or worse.

## 2. Evaluation framework (assignment 3.10)

### Golden dataset

A version-controlled dataset (`eval/datasets/<name>.jsonl`, one row per case):

```json
{
  "id": "contracts-001",
  "question": "What is the notice period for contract termination?",
  "expected_source": {"filename": "Client_Contracts_Policies_and_Incident_Records.pdf", "page_number": 4},
  "expected_answer": "30 days written notice",
  "content_type_hint": "page_text_plus_ocr"
}
```

Built by hand-curating question/source/answer triples against the two documents already in
this repo (`data/Client_Contracts_Policies_and_Incident_Records.pdf`,
`data/llama2-research-paper.pdf`) plus deliberately including table- and image-sourced
questions so multimodal retrieval quality (`05-multimodal-strategy.md`) is measured, not just
text. Grows over time as real production queries surface gaps (a query that got a thumbs-down
via `message_feedback`, once reviewed, becomes a new eval case).

### Metrics

| Metric | Measures | How |
|---|---|---|
| Retrieval recall@k / precision@k | Did the right chunk(s) show up in the top-K before generation? | Compare retrieved `document_id`/`page_number` against `expected_source` |
| Groundedness | Is the answer supported by the retrieved context, not hallucinated? | LLM-as-judge: given (answer, retrieved context), judge asks "is every claim in the answer traceable to the context?" |
| Answer correctness | Does the answer match `expected_answer` in substance? | LLM-as-judge semantic comparison (exact string match is too brittle for free-text answers) |
| Citation correctness | Do the returned `sources` actually match where the answer's claims came from? | Compare `sources[].citation` against `expected_source`; flag answers that cite the wrong page even if the answer text happens to be right |
| Latency | End-to-end and per-stage (retrieval vs. generation) response time | Captured from OpenTelemetry spans (§3), aggregated p50/p95/p99 |
| Token/model cost | $ per query, per workspace, per tenant | `messages.usage_json` (already returned by `src/generation.py::_usage_metadata`) aggregated with model pricing |
| Failure rate | Fraction of queries that error, time out, or return "I could not find enough relevant information" | Count of `generation_no_retrieval_results` / exceptions logged today, aggregated over time |

### Comparability across releases

Every eval run is executed against the frozen golden dataset and produces a report
(`eval/reports/<run_id>.json`) tagged with: model name, prompt version, chunking config
(`chunk_size`/`chunk_overlap`), retrieval config (hybrid on/off, reranker on/off, k), and git
commit. Reports are diffable — a spec that changes chunking or retrieval (per
`04-retrieval-design.md`) must include a before/after eval report in its `plan.md`/PR, not
just claim improvement. This is what turns "we upgraded to hybrid retrieval" into a testable
claim.

### How it runs

A CLI/script (`eval/run.py`) callable in CI on a schedule and on-demand locally, using
`packages/retrieval` and `packages/generation` directly (same code path production uses —
not a reimplementation) against a pinned Qdrant collection snapshot or a dedicated eval
workspace, so eval runs are reproducible and don't pollute production usage metrics.

## 3. Observability

### Tracing

OpenTelemetry instrumentation across `apps/api` and `packages/*`, with one trace per request
spanning: auth check -> retrieval (dense span, sparse span, fusion span, rerank span) ->
generation (prompt build span, LLM call span). Exported to an LLM-aware tracing backend
(Langfuse or Arize Phoenix) so prompts, retrieved context, and model outputs are inspectable
per-trace — not just latency numbers — which is what makes debugging "why did this answer go
wrong" tractable in production versus grepping log files.

### Metrics

Prometheus counters/histograms exported from `apps/api` and workers: request rate, error
rate, latency histograms per route, queue depth and job duration per `ingestion_jobs` stage,
Qdrant query latency, LLM call latency and token counts. Grafana dashboards per the
assignment's "admin analytics" and "usage quotas" product capabilities, backed by the same
`usage_quotas`/`audit_log` tables in `02-data-model.md`.

### Error tracking

Sentry (or equivalent) for unhandled exceptions across `apps/api`, workers, and `apps/web`,
replacing/augmenting the current pattern of catching everything into
`DocumentPortalException` and logging it (`exception/custom_exception.py`) — that pattern is
kept for structured internal errors, but unhandled exceptions additionally get captured with
full context for alerting.

### Feedback loop

`message_feedback` (thumbs up/down, `02-data-model.md`) is surfaced in an admin dashboard;
a down-voted message with reviewer annotation is the primary source of new eval cases,
closing the loop between production usage and the golden dataset in §2.

## 4. Related docs

- `04-retrieval-design.md` — the pipeline whose quality this section measures
- `05-multimodal-strategy.md` — image/table-specific retrieval quality, measured the same way
- `02-data-model.md` — `messages`, `message_feedback`, `usage_quotas`, `audit_log` schemas
