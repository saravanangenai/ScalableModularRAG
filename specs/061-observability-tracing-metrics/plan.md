# Plan: Observability — Tracing, Metrics, Error Tracking

- **Spec:** [spec.md](spec.md) (approved 2026-09-15)
- **Status:** in-progress — done except Sentry live-verification (deferred by user choice)

## Summary

OpenTelemetry tracing exported via OTLP to a locally-run, native-binary Jaeger instance (not
Langfuse/Phoenix — both are LLM-observability-focused and this repo has no generation/prompt
surface yet to make that specialization pay off; revisit when `packages/generation` exists).
Prometheus metrics from `apps/api` (via `prometheus-fastapi-instrumentator`, the standard
FastAPI integration) and from `workers` (via `prometheus_client.start_http_server` inside the
worker process, avoiding a separate Pushgateway). Grafana dashboards as version-controlled
JSON. Sentry via its hosted free tier — unlike Jaeger/Prometheus/Grafana, self-hosting Sentry
is a genuinely heavy multi-service operation, out of proportion to what this project needs.

All three new backends (Jaeger, Prometheus, Grafana) ship native Windows binaries — no Docker
required, consistent with every other local-infra decision this project has made (Postgres,
Keycloak, MinIO all run the same way). Resolves all three of `spec.md`'s open questions.

## Architecture doc deltas

| Doc | Change |
|---|---|
| `07-evaluation-observability.md` | §3: replace "Langfuse or Arize Phoenix" with the concrete decision (Jaeger via OTLP) and note the LLM-aware-backend move is deferred to whenever `packages/generation` exists; mark tracing/metrics/error-tracking as implemented. |

## Component/module ownership

- **`pyproject.toml`** — new dependencies: `opentelemetry-api`, `opentelemetry-sdk`,
  `opentelemetry-exporter-otlp-proto-http`, `opentelemetry-instrumentation-fastapi`,
  `opentelemetry-instrumentation-celery`, `prometheus-fastapi-instrumentator`,
  `prometheus-client`, `sentry-sdk`.
- **`packages/observability/tracing.py`** (new) — `configure_tracing(service_name: str)`:
  sets up an OTel `TracerProvider` with an OTLP HTTP exporter pointed at the local Jaeger
  instance's OTLP endpoint, called once at `apps/api`/worker startup, mirroring
  `configure_logging`'s existing "call once" pattern. `get_tracer(name)` re-exported for
  modules to pull their own tracer, same shape as `get_logger`.
- **`packages/observability/sentry.py`** (new) — `configure_sentry(dsn: str | None,
  environment: str)`: no-ops if `dsn` is `None` (so local dev without a configured Sentry
  project still runs fine), otherwise initializes `sentry_sdk` with the FastAPI and Celery
  integrations.
- **`packages/observability/config.py`** (new) — `Settings`: `otel_exporter_endpoint: str =
  "http://localhost:4318"` (Jaeger's default OTLP-HTTP port), `sentry_dsn: str | None =
  None`, `environment: str = "local"`.
- **`packages/observability/metrics.py`** (new) — the "custom Celery-side counters/
  histograms" the dashboard bullet below references, named explicitly here since they
  didn't have a home until implementation: `INGESTION_STAGE_DURATION` (Histogram, label
  `stage`), `INGESTION_JOBS_TOTAL` (Counter, label `status`), `RETRIEVAL_STAGE_DURATION`
  (Histogram, label `stage` — covers dense/sparse/fusion/rerank, doubling as the "Qdrant/
  embedding/rerank call latency" data source). Wired into the same span call sites Group 2
  added, not a separate pass over the code.
- **`apps/api/main.py`** — calls `configure_tracing("mm-rag-api")` and `configure_sentry(...)`
  in `create_app()`, alongside the existing `configure_logging()`-equivalent (currently only
  called in `workers/celery_app.py` — `apps/api` doesn't call it today either, a pre-existing
  gap noted but not fixed here since it's out of this spec's scope); mounts
  `prometheus_fastapi_instrumentator.Instrumentator().instrument(app).expose(app)` for the
  `/metrics` endpoint and automatic request-rate/latency/error-rate histograms per route.
  **Deviation, found during Group 4 live verification:** also calls
  `FastAPIInstrumentor.instrument_app(app)` (not originally listed here). Without it, every
  manually-added span (`auth.resolve_workspace_access`, `retrieval.dense_search`, etc.) had
  no parent HTTP-request span to nest under, so a single search request produced five
  disconnected root traces in Jaeger instead of one connected trace — failing the spec's
  "a full trace appears... auth → dense/sparse/fusion/rerank" acceptance criterion.
  `FastAPIInstrumentor` creates that root span; already a listed dependency
  (`opentelemetry-instrumentation-fastapi`), so no new dependency, just a missed call.
  A second, non-obvious ordering issue surfaced adding it: `FastAPIInstrumentor.
  instrument_app(app)` must be called **before**
  `Instrumentator().instrument(app).expose(app)` (prometheus), not after — calling
  Instrumentator first left `app.middleware_stack` already built by the time
  FastAPIInstrumentor patched `build_middleware_stack`, so the patched version was cached
  but never invoked and no request ever produced a span (confirmed empirically: swapping
  the two calls' order, plus a full process restart — WatchFiles' file-watcher missed the
  reorder edit and kept serving stale code once, another live-verification-only surprise —
  fixed it; verified via a real search request producing one connected trace: root `POST
  /workspaces/{workspace_id}/search` span with `auth.resolve_workspace_access`,
  `retrieval.dense_search`, `retrieval.sparse_search`, `retrieval.fusion`,
  `retrieval.rerank` all as direct children).
- **`apps/api/deps/rbac.py::require_workspace_role`** — wraps its body in a
  `tracer.start_as_current_span("auth.resolve_workspace_access")` span (covers both the
  JWT and API-key branches) — the one span this spec's acceptance criteria explicitly name
  for the search-request trace.
- **`packages/retrieval/{dense,sparse,fusion,rerank}.py`** — each public function wraps its
  body in its own named span (`retrieval.dense_search`, `retrieval.sparse_search`,
  `retrieval.fusion`, `retrieval.rerank`) — purely additive, no logic change, so this
  doesn't conflict with `060`'s sibling constraint that `packages/retrieval` stay behavior-
  unchanged for *that* spec (tracing is instrumentation, not pipeline behavior).
- **`packages/ingestion/pipeline.py::run_ingestion`** — each existing stage transition
  (`parsing`, `chunking`, `embedding`, `indexing`) becomes a span, plus two new sub-spans
  *within* the parsing stage for `050`/`051`'s additions (`ingestion.vision_captioning`,
  `ingestion.table_summarization`) so they're visible as their own timed segments instead of
  folded into one undifferentiated "parsing" block — directly satisfying the acceptance
  criterion that names them.
- **`workers/celery_app.py`** — calls `configure_tracing("mm-rag-worker")`,
  `configure_sentry(...)`, and `prometheus_client.start_http_server(9100)` **inside a
  `celery.signals.worker_init` handler, not at bare module scope as originally written
  here.** **Deviation, found during Group 4 live verification:** `apps/api/routers/
  documents.py` does `from workers.celery_app import run_ingestion_job` to enqueue jobs, so
  importing `apps.api.main` transitively imports and executes this module's top level too.
  With the calls at bare module scope, that import ran `configure_tracing("mm-rag-worker")`
  *before* `create_app()` reached its own `configure_tracing("mm-rag-api")` call;
  `tracing.py`'s `_configured` idempotency guard then silently no-op'd the correct call,
  permanently mislabeling every span the API process ever created as `mm-rag-worker`. The
  same import also made the API process bind `prometheus_client.start_http_server(9100)`
  before the real worker process got a chance to — confirmed live via `netstat` showing two
  listeners on `:9100` (the uvicorn PID and the real worker PID) until this fix. `worker_init`
  fires exactly once, only when this module is running as the actual `celery worker` command
  (true for `--pool=solo` too, unlike `worker_process_init` which is prefork-specific) — never
  on a plain import. Celery's OTel auto-instrumentation (`CeleryInstrumentor().instrument()`)
  moved into the same handler for the same reason; it wraps `run_ingestion_job` for a
  top-level job span automatically, with the manual spans above nested inside it.
- **`infra/prometheus.yml`** (new) — scrape config: `apps/api`'s `/metrics` and the worker's
  `:9100` endpoint.
- **`infra/grafana/dashboards/platform-overview.json`** (new) — version-controlled
  dashboard: request rate/error rate/latency percentiles per route (from
  `prometheus-fastapi-instrumentator`'s metrics), ingestion job throughput and per-stage
  duration (from custom Celery-side counters/histograms this spec adds alongside the spans
  above), Qdrant/embedding/rerank call latency.
- **`start_services_from_terminal.txt`** — updated with the three new native-binary services
  (Jaeger, Prometheus, Grafana) and their default ports, matching how Keycloak/MinIO were
  already documented there.

## Data model changes

None. No Postgres/Qdrant schema changes.

## API contract

- New: `GET /metrics` on `apps/api` (Prometheus scrape format, not JSON) — exposed by
  `prometheus-fastapi-instrumentator`, unauthenticated (matches Prometheus's standard
  same-network-trust model; not exposing anything beyond aggregate counters/histograms, no
  per-request/user data).
- No changes to any existing route's request/response shape or auth requirement.

## Retrieval / ingestion impact

- Spans add negligible overhead (microseconds per span in the OTel SDK's in-process buffer;
  actual export to Jaeger happens on a background thread/batch, not inline with the request)
  — not expected to be measurable against the multi-hundred-millisecond LLM/embedding calls
  already dominating these code paths.
- No behavior change to retrieval ranking or ingestion output — instrumentation only.

## Security / tenancy impact

- Spans/traces must not carry secrets or PII beyond what's already appropriate to log —
  `Authorization` headers and provider API keys are never added as span attributes (only
  non-sensitive fields: `workspace_id`, `query` length, result counts, stage names,
  durations). `query` *text* itself is arguably sensitive (could contain a user's contract
  question) — excluded from span attributes by default, consistent with
  `06-security-model.md` §6's "provider API keys are held by backend services only" stance
  extended here: traces are an internal-network tool but shouldn't casually accumulate
  searchable-forever copies of user query text without a deliberate decision to do so.
- `/metrics` exposes aggregate counters only (no per-workspace or per-user breakdown in this
  increment) — cannot be used to enumerate which workspaces exist or infer their activity
  individually.
- No change to `build_workspace_filter`, RLS, or any auth code path's actual authorization
  logic — only additive span wrapping around already-existing checks.

## Rollout

Big-bang, no flag:
- Tracing/metrics/Sentry are additive and fail open: if Jaeger/Prometheus aren't running
  locally, the OTel SDK buffers and drops spans without raising (standard OTel exporter
  behavior) — `apps/api`/workers keep functioning normally without the observability stack
  up, same as how this project already runs fine without a Celery worker for
  non-ingestion-touching tests.
- `configure_sentry` no-ops entirely with no `SENTRY_DSN` configured — local dev never
  requires a Sentry account.
- Revert path: remove the `configure_tracing`/`configure_sentry` calls and the
  `Instrumentator` mount; the per-function span context managers are inert if the SDK is
  never configured (spans just aren't exported), so leaving them in place after a partial
  revert is harmless.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Jaeger/Prometheus/Grafana native Windows binaries have setup friction not discoverable until actually installing them (the MinIO lesson from `030`) | Medium — this project has already hit one "assumed-available, actually discontinued" infra surprise | Low-Medium — same recovery pattern as MinIO (checksum-verify an alternate source, or fall back to a hosted free tier) if a binary turns out to be unavailable | Verify each binary's actual current availability during Stage 4 implementation, not assumed here — flagged explicitly so this isn't silently glossed over the way it almost was before |
| Instrumenting every retrieval-leg function with spans adds a small but real amount of boilerplate/noise to `packages/retrieval`, which `060`'s plan deliberately kept untouched | Low | Low — span context managers are a thin wrapper, not logic change, and both specs were sequenced so `061` lands after `060`'s comparison work is already using the un-instrumented functions | Land `060` first if not already done, so its before/after report is captured against the pre-tracing code, purely as a clean sequencing choice, not a hard requirement |
| Celery's OTel auto-instrumentation and the manual per-stage spans inside `run_ingestion` could double-count or nest confusingly | Low | Low — cosmetic (a confusing trace tree), not a correctness issue | Verify the actual trace tree shape in Jaeger's UI during Stage 4 before calling this acceptance criterion met, not just trusting the libraries compose cleanly on paper |

## Alternatives considered

- **Langfuse or Arize Phoenix** (the architecture doc's named suggestions) — rejected for
  now: both are LLM-observability platforms whose main value (prompt/output inspection per
  trace) has nothing to instrument yet, since `packages/generation` doesn't exist. A
  general-purpose OTel backend (Jaeger) covers this repo's actual current surface
  (retrieval/ingestion spans) without paying for LLM-specific features that would sit empty.
  Revisit when a generation spec lands — swapping the OTLP exporter's endpoint is a small
  change, not a re-instrumentation, since the spans themselves are already OTel-standard.
- **Self-hosted Sentry** — rejected: Sentry's self-hosted deployment is a multi-service stack
  (their own docs describe it as Docker-Compose-orchestrated, 10+ containers) that doesn't
  fit this project's no-Docker-available, native-binary pattern at all; the hosted free tier
  is the only realistic fit here.
- **Prometheus Pushgateway for worker metrics** instead of `start_http_server` inside the
  worker process — rejected: Pushgateway is meant for short-lived batch jobs that can't be
  scraped directly; this project's Celery worker is a long-running process Prometheus can
  scrape directly, so Pushgateway would be an unnecessary extra service.
