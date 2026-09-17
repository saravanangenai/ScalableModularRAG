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

**Status:** the golden dataset, `eval/` CLI, and recall@k/precision@k/MRR/latency metrics
below are implemented and retrieval-only, as of `060-retrieval-evaluation`. Groundedness,
answer correctness, citation correctness, and token/model cost (all below) remain deferred —
they require a generation pipeline, which doesn't exist yet in this repo (roadmap: after
Phase 8). Comments below describing implementation are accurate for the retrieval slice
only; anything mentioning `packages/generation` is still aspirational.

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

A CLI/script (`eval/run.py`) callable in CI on a schedule and on-demand locally. As
implemented (`060-retrieval-evaluation`), it composes `packages/retrieval`'s public
functions directly (same code path production uses, not a reimplementation) against a
dedicated eval workspace, so eval runs are reproducible and don't pollute production usage
metrics. `packages/generation` doesn't exist yet, so generation-stage metrics (groundedness,
answer correctness, citation correctness, cost) aren't produced by this CLI — that's future
scope once a generation pipeline lands.

## 3. Observability

**Status:** tracing and metrics below are implemented and live-verified end-to-end
(`061-observability-tracing-metrics`). Error tracking (Sentry) is implemented in code
(`packages/observability/sentry.py::configure_sentry`, wired into both `apps/api` and
`workers`) but not yet live-verified — it requires a real Sentry account/DSN, which wasn't
provisioned in this increment; `configure_sentry(dsn=None, ...)` no-ops safely, so local dev
and CI run fine without one. `apps/UI` doesn't exist yet, so it isn't wired anywhere.

### Tracing

OpenTelemetry instrumentation across `apps/api`, `workers`, and `packages/retrieval`/
`packages/ingestion`, exported via OTLP-HTTP to a locally-run, native-binary **Jaeger v2**
instance (not Langfuse/Arize Phoenix as originally sketched here — both are
LLM-observability platforms whose main value, prompt/output inspection, has nothing to
instrument yet since `packages/generation` doesn't exist; revisit when a generation spec
lands, since the spans themselves are already OTel-standard and swapping the OTLP endpoint
is a small change, not a re-instrumentation). Live-verified trace shapes:
- A search request produces one connected trace: root `POST /workspaces/{workspace_id}/
  search` (`opentelemetry-instrumentation-fastapi`'s auto span) with
  `auth.resolve_workspace_access`, `retrieval.dense_search`, `retrieval.sparse_search`,
  `retrieval.fusion`, `retrieval.rerank` as direct children.
- An ingestion job produces one connected trace: root `run/workers.celery_app.
  run_ingestion_job` (Celery's OTel auto-instrumentation) with `ingestion.parsing`,
  `ingestion.chunking`, `ingestion.embedding`, `ingestion.indexing` as children, and
  `ingestion.vision_captioning`/`ingestion.table_summarization` nested inside `parsing`.

### Metrics

Prometheus counters/histograms exported from `apps/api` (`/metrics`, via
`prometheus-fastapi-instrumentator`: request rate, error rate, latency histograms per route)
and from `workers` (`:9100`, via `prometheus_client`: `ingestion_stage_duration_seconds`,
`ingestion_jobs_total`) — plus `retrieval_stage_duration_seconds` (dense/sparse/fusion/
rerank latency), recorded wherever each leg runs (`apps/api` for search requests). Grafana
dashboard (`infra/grafana/dashboards/platform-overview.json`, version-controlled) live-
verified with real data from an actual search request and ingestion job. LLM call
token/cost counts remain future scope, tied to `packages/generation`.

`070-api-hardening`'s rate-limit `429` responses are a new, expected error class visible in
`http_requests_total{status="429"}` — no new metric needed, the instrumentation above
already captures any status code a route returns.

### Error tracking

Sentry via its hosted free tier (not self-hosted — self-hosting is a multi-service stack out
of proportion to this project's no-Docker, native-binary pattern) for unhandled exceptions
across `apps/api` and `workers`, replacing/augmenting the current pattern of catching
everything into `DocumentPortalException` and logging it — that pattern is kept for
structured internal errors, but unhandled exceptions additionally get captured with full
context for alerting once a `SENTRY_DSN` is configured. `apps/UI` doesn't exist yet.

### Feedback loop

`message_feedback` (thumbs up/down, `02-data-model.md`) is surfaced in an admin dashboard;
a down-voted message with reviewer annotation is the primary source of new eval cases,
closing the loop between production usage and the golden dataset in §2.

## 4. Related docs

- `04-retrieval-design.md` — the pipeline whose quality this section measures
- `05-multimodal-strategy.md` — image/table-specific retrieval quality, measured the same way
- `02-data-model.md` — `messages`, `message_feedback`, `usage_quotas`, `audit_log` schemas
