# Spec: Observability — Tracing, Metrics, Error Tracking

- **ID:** `061-observability-tracing-metrics`
- **Roadmap phase:** [08-roadmap.md](../architecture/08-roadmap.md) Phase 7 — Evaluation +
  Observability (`060-069`), the cross-cutting-infrastructure half —
  [`07-evaluation-observability.md`](../architecture/07-evaluation-observability.md) §3.
  Sibling to `060-retrieval-evaluation` (golden-dataset quality measurement) — split out
  because this is infrastructure instrumentation across the existing system, not a
  measurement exercise against `packages/retrieval` specifically; the two don't share code.
- **Status:** in-progress — done except Sentry live-verification (needs a real account,
  deferred by user choice; code complete, safe without a DSN)
- **Owner:** Saravanan Shanmugam
- **Date:** 2026-09-16

## Problem statement

`packages/observability/structured_logging.py` gives every service structured,
`snake_case_event_name` logs (`configure_logging`, already used by `apps/api` and
`workers/celery_app.py`) — a real foundation, but logs alone don't answer "why was this
specific request slow," "which stage of ingestion is the bottleneck across many jobs," or
"page someone when the error rate spikes." There is no distributed tracing (a request's
journey through auth → retrieval's four legs → indexing isn't visible as one connected
trace), no aggregated metrics (latency percentiles, queue depth, per-route error rate all
require grepping logs by hand today), and no error alerting (an unhandled exception is only
as visible as whoever happens to be tailing worker/API logs at the time).

## Goals

- OpenTelemetry instrumentation across `apps/api` and `packages/*`, producing one trace per
  request spanning at minimum: auth/RBAC resolution, each retrieval leg (dense, sparse,
  fusion, rerank — `packages/retrieval`), and ingestion's per-stage transitions (parsing,
  chunking, embedding, indexing — `packages/ingestion/pipeline.py`, already named stages
  from `020`/`03-ingestion-workflow.md`, now made visible as spans instead of only status
  transitions in Postgres).
- Traces exported somewhere inspectable — per `07-evaluation-observability.md` §3's
  suggestion (Langfuse or Arize Phoenix, LLM-aware tracing that shows prompts/retrieved
  context/outputs per-trace, not just latency numbers) or a simpler OTel-compatible backend
  if the LLM-specific features aren't justified yet given `packages/generation` doesn't
  exist (no prompts/LLM outputs to inspect on the retrieval-only path this repo currently
  has) — resolved in `plan.md`.
- Prometheus counters/histograms from `apps/api` and `workers`: request rate, error rate,
  and latency histograms per route; `ingestion_jobs` queue depth and per-stage duration;
  Qdrant query latency; embedding/rerank call latency.
- Grafana dashboards over those metrics — request/error/latency for the API, ingestion
  throughput and failure rate for the worker.
- Sentry (or equivalent) capturing unhandled exceptions across `apps/api` and `workers`,
  additive to (not replacing) the existing `DocumentPortalException` structured-error
  pattern — that pattern stays for expected/handled failure modes; this adds visibility for
  the unexpected ones.

## Non-goals

- **Not** the golden-dataset eval framework or retrieval-quality metrics (recall@k,
  precision@k) — that's the sibling spec `060-retrieval-evaluation`.
- **Not** tracing/metrics for `apps/web` or `apps/streamlit-admin` — neither exists yet
  (both are empty scaffolding per `09-repo-and-module-structure.md`); this spec instruments
  what's actually running (`apps/api`, `workers`).
- **Not** the feedback loop or an admin analytics dashboard surfacing `message_feedback` —
  deferred with `060`, for the same reason (no chat/messages pipeline exists yet to generate
  feedback from).
- **Not** usage-quota enforcement dashboards — `usage_quotas` doesn't exist in the
  single-tenant as-built schema (`012` dropped it; `02-data-model.md` §0). Grafana
  dashboards here are request/error/latency/ingestion-health, not billing/quota views.
- **Not** alerting rules/on-call configuration beyond Sentry's own default unhandled-exception
  capture — routing/paging policy is an ops decision outside this spec's scope.
- **Not** a change to any request/business logic — this is additive instrumentation around
  existing code paths, not a behavior change.

## User-facing behavior

No end-user UI; this is operator/developer-facing.

- A request to any `apps/api` route produces one trace showing every stage it passed
  through and how long each took, inspectable in the tracing backend — not just an
  aggregate latency number.
- An ingestion job's per-stage timing (parsing/chunking/embedding/indexing) is visible as a
  trace, not just as `ingestion_jobs.status` transitions in Postgres (which show *that* a
  stage happened, not how long it took relative to the others).
- A Grafana dashboard shows request rate, error rate, and latency percentiles for `apps/api`
  routes, and ingestion job throughput/failure rate for the worker, without needing to query
  Postgres or grep logs by hand.
- An unhandled exception anywhere in `apps/api` or `workers` shows up in Sentry with full
  context (stack trace, request/job context), not just a log line that scrolls away.

## Acceptance criteria

- [x] A request to `POST /workspaces/{workspace_id}/search` produces a trace with distinct
      spans for auth/RBAC resolution and each of the dense/sparse/fusion/rerank legs, visible
      in the chosen tracing backend.
      Verified live in Jaeger: one connected trace, root `POST /workspaces/{workspace_id}/
      search` with `auth.resolve_workspace_access`, `retrieval.dense_search`,
      `retrieval.sparse_search`, `retrieval.fusion`, `retrieval.rerank` as direct children.
- [x] An ingestion job produces a trace with distinct spans for each pipeline stage
      (parsing/chunking/embedding/indexing), including the sub-steps `050`/`051` added
      (vision captioning, table summarization) as their own spans, not folded into "parsing"
      as one opaque block.
      Verified live in Jaeger against a real ingestion job: root `run/workers.celery_app.
      run_ingestion_job` with `ingestion.parsing`/`chunking`/`embedding`/`indexing` as
      children, `vision_captioning`/`table_summarization` correctly nested inside `parsing`.
- [x] `apps/api` exposes a Prometheus-scrapeable metrics endpoint with request rate, error
      rate, and latency histograms per route.
      `/metrics` live; Prometheus target `mm-rag-api` confirmed `up`.
- [x] `workers` exposes or pushes metrics for `ingestion_jobs` queue depth and per-stage
      duration.
      `:9100` live (`ingestion_jobs_total`, `ingestion_stage_duration_seconds`); Prometheus
      target `mm-rag-worker` confirmed `up`; real data confirmed
      (`ingestion_jobs_total{status="ready"}=1` after a real ingestion job).
- [x] A Grafana dashboard (version-controlled definition, not a manually-clicked-together
      one) renders the metrics above.
      `infra/grafana/dashboards/platform-overview.json`, imported and confirmed loading
      (200) with all 6 panels; underlying PromQL confirmed returning real data.
- [ ] An unhandled exception raised in `apps/api` or a Celery task is captured in Sentry
      with request/job context attached, verified by deliberately triggering one in a test
      environment.
      **Deferred**: no Sentry account provisioned this increment (user's explicit choice —
      `configure_sentry` implemented and wired into both `apps/api` and `workers`, no-ops
      safely without a DSN). Revisit once `SENTRY_DSN` exists.
- [x] `uv run pytest tests/unit` passes with no live services (span/metric instrumentation
      code that doesn't require a live collector is unit-testable; a live trace/metrics/error
      capture is verified against the real stack, documented as such).
      133 passed.
- [x] `030`'s and `040`'s existing authorization/hybrid-search test suites still pass
      unmodified — instrumentation must not change request behavior or error codes.
      Full `tests/integration` suite (37 tests, includes `030`/`040`'s suites): 37 passed in
      14m51s.

## Constraints

- Python 3.12, `uv`-managed.
- Must not weaken the existing `DocumentPortalException` error-wrapping convention —
  Sentry/tracing are additive observability, not a replacement for structured internal
  errors.
- Must not log or trace secrets (API keys, JWTs, provider credentials) — spans/traces must
  redact or omit `Authorization` headers and provider API keys, consistent with
  `06-security-model.md` §6's "provider API keys are held by backend services only" stance
  extended to telemetry, not just request handling.
- New observability backends (tracing/metrics/error-tracking services) must be runnable
  locally without a paid account where a free/self-hosted option exists, consistent with
  every prior infrastructure choice this project has made (Qdrant Cloud's free tier,
  self-hosted Keycloak, self-hosted MinIO) — confirmed per-choice in `plan.md`, not assumed.
- Must not regress any `020`/`030`/`040`/`050`/`051` acceptance criteria — the full existing
  integration suite must still pass.
- Local dev/test must stay runnable the way `051` verified it.

## Open questions

1. **Tracing backend.** Langfuse and Arize Phoenix (the doc's named suggestions) are both
   LLM-observability-focused — most valuable once `packages/generation` exists and there are
   prompts/LLM outputs to inspect per-trace. Given this repo's current retrieval-only
   surface, is a general-purpose OTel backend (e.g. self-hosted Jaeger/Grafana Tempo) a
   better fit for now, with a move to an LLM-aware backend deferred alongside generation? →
   `plan.md`.
2. **Metrics/dashboard hosting.** Self-hosted Prometheus + Grafana (matching this project's
   "native services, no Docker requirement where avoidable" pattern established for
   Postgres/Keycloak) vs. a hosted free tier (e.g. Grafana Cloud's free tier) — confirm which
   before locking in `plan.md`'s infra choice, the same way MinIO/Qdrant Cloud decisions were
   made explicitly rather than assumed.
3. **Sentry account/hosting.** Sentry's hosted free tier vs. self-hosted (heavier
   install) — given this project's local-dev-first, low-infra-footprint pattern, leaning
   hosted free tier for Sentry specifically (self-hosting Sentry is a notably heavier
   operational lift than the other choices here), but confirm before `plan.md`.
