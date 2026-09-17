# Tasks: Observability — Tracing, Metrics, Error Tracking

- **Plan:** [plan.md](plan.md) (approved 2026-09-16)
- **Status:** in-progress — Groups 1-4 done except Sentry account/live-verification
  (deferred, user's choice; code complete and safe without a DSN)

Work top to bottom. Each group should leave the system in a runnable state. Check items off
with `- [x]` as completed; do not delete or renumber finished items.

## Group 1 — Dependencies + config + tracing/Sentry helpers

- [x] Add `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`,
      `opentelemetry-instrumentation-fastapi`, `opentelemetry-instrumentation-celery`,
      `prometheus-fastapi-instrumentator`, `prometheus-client`, `sentry-sdk` to
      `pyproject.toml`, run `uv sync`. — files: `pyproject.toml` — verify: each package
      imports clean in a one-off `uv run python -c "import ..."` check. Confirmed.
- [x] Add `packages/observability/config.py::Settings` (`otel_exporter_endpoint: str =
      "http://localhost:4318"`, `sentry_dsn: str | None = None`, `environment: str =
      "local"`). — files: `packages/observability/config.py` (new) — verify: new
      `tests/unit/test_observability_config.py` asserting defaults. 1 passed.
- [x] Add `packages/observability/tracing.py::configure_tracing(service_name)` +
      `::get_tracer(name)`, mirroring `structured_logging.py`'s `configure_logging`/
      `get_logger` shape. — files: `packages/observability/tracing.py` (new) — verify: new
      `tests/unit/test_observability_tracing.py` — calling `configure_tracing` twice doesn't
      raise (idempotent-safe for tests/reloads), `get_tracer` returns a real
      `opentelemetry.trace.Tracer`. 2 passed.
- [x] Add `packages/observability/sentry.py::configure_sentry(dsn, environment)` — no-ops
      when `dsn` is `None`. — files: `packages/observability/sentry.py` (new) — verify: new
      `tests/unit/test_observability_sentry.py` — `dsn=None` doesn't call `sentry_sdk.init`
      (mocked), a real DSN string does. 2 passed.

## Group 2 — Instrument `packages/retrieval` and `packages/ingestion`

- [x] Wrap `dense_search`, `sparse_search`, `reciprocal_rank_fusion`, `rerank` bodies in
      named spans (`retrieval.dense_search`, etc.) via `get_tracer(__name__)`. — files:
      `packages/retrieval/dense.py`, `packages/retrieval/sparse.py`,
      `packages/retrieval/fusion.py`, `packages/retrieval/rerank.py` — verify:
      `uv run pytest tests/unit/test_retrieval_search.py tests/unit/test_retrieval_sparse.py
      tests/unit/test_retrieval_fusion.py tests/unit/test_retrieval_rerank.py` — all still
      pass unmodified (spans must not change return values, call signatures, or error
      behavior for any existing test). 20 passed.
- [x] Wrap `run_ingestion`'s stage transitions in spans (`ingestion.parsing`,
      `ingestion.chunking`, `ingestion.embedding`, `ingestion.indexing`) plus two new
      sub-spans within parsing (`ingestion.vision_captioning`, wrapping the per-image
      captioning loop; `ingestion.table_summarization`, wrapping the per-table loop). —
      files: `packages/ingestion/pipeline.py` — verify: `uv run pytest tests/unit` — no
      regressions (same "no dedicated `run_ingestion` unit test" convention noted in
      `050`/`051` — live-verified in Group 4). 130 passed; span-export attempted and failed
      open (Jaeger not running yet) exactly as `plan.md`'s Rollout section expects.
- [x] Wrap `apps/api/deps/rbac.py::require_workspace_role`'s dependency body in an
      `auth.resolve_workspace_access` span, covering both the JWT and API-key branches. —
      files: `apps/api/deps/rbac.py` — verify: `uv run pytest
      tests/unit/test_auth_rbac.py` (no regressions) — full live trace shape confirmed in
      Group 4. Included in the 130-pass run above.

## Group 3 — Wire `apps/api` and `workers` into tracing/metrics/Sentry

- [x] In `apps/api/main.py::create_app`, call `configure_tracing("mm-rag-api")` and
      `configure_sentry(settings.sentry_dsn, settings.environment)`; mount
      `prometheus_fastapi_instrumentator.Instrumentator().instrument(app).expose(app)` for
      `GET /metrics`. — files: `apps/api/main.py` — verify: `uv run python -c "from
      apps.api.main import app; print(len(app.routes))"` shows the new `/metrics` route
      alongside the existing ones (no import errors even with Jaeger/Prometheus not running
      yet — OTel exporters must not fail startup when their target is unreachable).
      Confirmed: 11 routes, `/metrics` present; import succeeds with no Jaeger running.
- [x] In `workers/celery_app.py`, call `configure_tracing("mm-rag-worker")`,
      `configure_sentry(...)`, and `prometheus_client.start_http_server(9100)` once at
      module scope; add `CeleryInstrumentor().instrument()` for automatic per-task spans. —
      files: `workers/celery_app.py` — verify: `uv run python -c "import
      workers.celery_app"` imports clean. Confirmed clean import.
- [x] Add `packages/observability/metrics.py` (custom Prometheus counters/histograms the
      dashboard below needs — not itemized as its own task originally, added here since
      `plan.md`'s dashboard bullet already called for "custom Celery-side counters/
      histograms"): `INGESTION_STAGE_DURATION`, `INGESTION_JOBS_TOTAL`,
      `RETRIEVAL_STAGE_DURATION`; wired into the same span call sites Group 2 added
      (`packages/retrieval/{dense,sparse,fusion,rerank}.py`,
      `packages/ingestion/pipeline.py`). — files: `packages/observability/metrics.py` (new),
      `tests/unit/test_observability_metrics.py` (new), plus the five files above — verify:
      3 new unit tests passed; full `uv run pytest tests/unit` still green (133 passed, up
      from 130).
- [x] Add `infra/prometheus.yml` (scrape config: `apps/api`'s `/metrics`, worker's `:9100`)
      and `infra/grafana/dashboards/platform-overview.json` (request rate/error rate/latency
      per route, ingestion throughput/per-stage duration, Qdrant/embedding/rerank latency —
      version-controlled, not manually clicked together). — files: `infra/prometheus.yml`
      (new), `infra/grafana/dashboards/platform-overview.json` (new). Both created; dashboard
      JSON validated to parse; live rendering with real data verified in Group 4.

## Group 4 — Install the local stack, live-verify, docs, regression

- [x] Download/verify Jaeger's native Windows all-in-one binary (check current official
      distribution first — this project already hit one "assumed available, actually
      discontinued" surprise with MinIO in `030`; don't repeat that here). Run it, confirm
      its UI is reachable and its OTLP-HTTP port (`4318`) accepts data. — files: none
      (environment setup) — verify: Jaeger UI loads in a browser.
      Jaeger v2.21.0 (SHA256-verified from the official GitHub release). Jaeger v2's binary
      is OTel-collector-based and needs `--config` (no more v1-style `jaeger-all-in-one`
      flags) plus a UI config file at a config-relative path — both fetched from the
      matching release tag. UI on `:16686` (200) and OTLP-HTTP on `:4318` (200) confirmed.
- [x] Download/verify Prometheus and Grafana native Windows binaries similarly. Point
      Prometheus at `infra/prometheus.yml`, load the dashboard JSON into Grafana. — files:
      none (environment setup) — verify: Prometheus's targets page shows `apps/api` and the
      worker as `UP`; Grafana renders the dashboard with real data once traffic flows.
      Prometheus 3.14.0 and Grafana 13.2.2 (both SHA256-verified; Grafana OSS Windows
      binaries ship from dl.grafana.com, not GitHub releases). Grafana required an absolute
      Windows `--homepath` — a relative `"."` made it fall back to a hardcoded
      `/usr/share/grafana/public` path and fail to start (documented in
      `start_services_from_terminal.txt`). Prometheus datasource + dashboard provisioned via
      Grafana's API; both `mm-rag-api` and `mm-rag-worker` targets confirmed `up`; dashboard
      loads (200) with all 6 panels, PromQL queries confirmed returning real data
      (`ingestion_jobs_total{status="ready"} = 1` after a real ingestion job).
- [ ] Create (or confirm) a Sentry account/project on the hosted free tier, set `SENTRY_DSN`
      in `infra/.env`. — files: `infra/.env` (user-provided secret, not committed) — verify:
      none yet (next task exercises it).
      **Deferred by user choice** (asked via AskUserQuestion during this Group): install and
      live-verify Jaeger/Prometheus/Grafana now, skip Sentry since it needs a real account
      the user has to create. `configure_sentry(dsn=None, ...)` no-ops safely, so this
      doesn't block anything else in this spec; revisit whenever a `SENTRY_DSN` exists.
- [x] Restart `apps/api` and the Celery worker with the new code + env vars. Send a real
      search request and confirm a full trace appears in Jaeger with the named spans
      (auth → dense/sparse/fusion/rerank). Trigger a real ingestion and confirm its trace
      shows parsing/chunking/embedding/indexing plus the vision-captioning/table-
      summarization sub-spans as distinct timed segments. — files: none — verify: both
      traces visually inspected in Jaeger's UI, span names and nesting match what `plan.md`
      specified (check for Celery-auto-instrumentation-vs-manual-span double-counting or
      confusing nesting per `plan.md`'s named risk).
      Found and fixed two real bugs live-verification surfaced (both documented in
      `plan.md`'s Component ownership section with full root-cause analysis): (1)
      `workers/celery_app.py`'s module-level `configure_tracing`/`configure_sentry`/
      `start_http_server(9100)` calls ran inside the API process too (via
      `apps/api/routers/documents.py`'s `from workers.celery_app import run_ingestion_job`),
      mislabeling every API-process span as `mm-rag-worker` and duplicate-binding port 9100
      — fixed by moving them into a `celery.signals.worker_init` handler, which only fires
      for the real worker process. (2) `FastAPIInstrumentor.instrument_app(app)` must be
      called *before* `Instrumentator().instrument(app).expose(app)`, not after — the wrong
      order left `app.middleware_stack` already built, so the OTel ASGI wrapping was patched
      but never invoked and zero spans were produced for any request. After both fixes:
      search request → one trace, root `POST /workspaces/{workspace_id}/search` with
      `auth.resolve_workspace_access`/`retrieval.dense_search`/`retrieval.sparse_search`/
      `retrieval.fusion`/`retrieval.rerank` as children. Real ingestion job → one trace, root
      `run/workers.celery_app.run_ingestion_job` with `ingestion.parsing`/`chunking`/
      `embedding`/`indexing` as children and `vision_captioning`/`table_summarization`
      correctly nested inside `parsing`. Both visually confirmed via Jaeger's v3 query API.
- [ ] Deliberately trigger an unhandled exception in a test/throwaway route or task and
      confirm it appears in Sentry with request/job context attached. — files: none —
      verify: event visible in the Sentry project dashboard.
      Deferred with the Sentry account task above.
- [x] Full regression: `uv run pytest tests/unit` and `uv run pytest tests/integration` both
      green — confirms instrumentation didn't change any request/job behavior or error
      codes. — files: none — verify: record pass counts here once run.
      `tests/unit`: 133 passed. `tests/integration`: 37 passed in 891.78s (0:14:51) — no
      regressions from instrumentation. DB schema restored via `alembic upgrade head`
      afterward (integration teardown wipes it, per established project convention).
- [x] Update `07-evaluation-observability.md` §3 per `plan.md`'s Architecture doc deltas;
      update `start_services_from_terminal.txt` with the three new services. — files:
      `specs/architecture/07-evaluation-observability.md`,
      `start_services_from_terminal.txt`.
- [x] `specs/README.md` gains a `061` row; status set to `in-progress` (Sentry
      account/live-verification deferred; everything else done and live-verified).

## Verification (end of increment)

- [x] All `spec.md` acceptance criteria satisfied, verified live (traces in Jaeger, metrics
      in Grafana, an error in Sentry) — not just "the code compiles." Traces in Jaeger and
      metrics in Grafana: yes, live-verified. An error in Sentry: deferred — no Sentry
      account provisioned this increment (user's explicit choice); `configure_sentry` is
      implemented and no-ops safely without a DSN.
- [x] `uv run pytest tests/unit` passes with no live services. 133 passed.
- [x] `uv run pytest tests/integration` passes against the full real stack (proves
      instrumentation didn't change behavior). 37 passed in 14m51s.
- [x] `07-evaluation-observability.md` updated per `plan.md`'s Architecture doc deltas.
- [x] `specs/README.md` gains a `061` row; status set to `in-progress` — Sentry
      account/live-verification is the only remaining item, tracked above, not blocking
      anything else in this spec or the roadmap.
