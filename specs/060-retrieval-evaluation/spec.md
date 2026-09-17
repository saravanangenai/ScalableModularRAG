# Spec: Retrieval Evaluation

- **ID:** `060-retrieval-evaluation`
- **Roadmap phase:** [08-roadmap.md](../architecture/08-roadmap.md) Phase 7 — Evaluation +
  Observability (`060-069`), the retrieval-quality-measurement half —
  [`07-evaluation-observability.md`](../architecture/07-evaluation-observability.md) §2.
  Sibling to `061-observability-tracing-metrics` (tracing/dashboards/error tracking) —
  split out because eval is a quality-measurement concern exercising `packages/retrieval`
  directly, while `061` is cross-cutting infrastructure instrumentation; they don't share
  code and can be reviewed/implemented independently.
- **Status:** done
- **Owner:** Saravanan Shanmugam
- **Date:** 2026-09-16

## Problem statement

Every retrieval-quality claim made across `040-hybrid-retrieval-reranking`,
`050-vision-captioning`, and `051-table-intelligence` was verified by hand: one lexical
query, one semantic image query, one table query, each checked once against the fixture PDF.
That was the right amount of rigor for implementing those phases (per each phase's own
non-goals — formal quality measurement was explicitly deferred to "Phase 7"), but there is
still no repeatable, versioned way to answer "did this retrieval change actually make things
better, and for which kinds of queries?" `04-retrieval-design.md` §4 names this directly:
the reranker's latency cost should be justified by "an eval framework that can measure this
pipeline with and without the reranker" — that framework doesn't exist yet.

`07-evaluation-observability.md` §2 describes a golden-dataset eval framework whose metrics
include answer correctness, groundedness, and citation correctness — all of which require an
LLM to have generated an answer from retrieved context. `packages/generation` is still empty
scaffolding (`.gitkeep` only); no phase before this one has built a chat/answer-synthesis
pipeline in this repo. Building those metrics now would mean evaluating a pipeline that
doesn't exist. This spec is scoped to what's actually measurable today: **retrieval quality
only** — recall@k/precision@k, latency, and comparability across retrieval configurations
(dense-only vs. hybrid, reranker on/off, `k`). Answer-quality metrics are deferred to a
follow-up spec once a generation pipeline exists.

## Goals

- A version-controlled golden dataset of retrieval cases (question + expected source
  document/page, no expected answer text) built against `tests/fixtures/sample.pdf` (or a
  fuller corpus if one exists by the time this is planned), deliberately including
  text-, table-, and image-sourced questions so `050`/`051`'s multimodal retrieval quality is
  measured specifically, not just text (`07-evaluation-observability.md` §2's own framing,
  narrowed to the retrieval-only metrics below).
- An eval CLI/script that runs the golden dataset through `packages/retrieval.search`
  directly (the same code path production uses, not a reimplementation) and produces a
  version-controlled report.
- Metrics: recall@k, precision@k (did the expected chunk appear in the top-K, compared
  against `expected_source`), and latency (end-to-end per query, aggregated).
- Reports are comparable across runs: each is tagged with retrieval config (hybrid on/off,
  reranker on/off, `k`, model names) and a git commit, so a future retrieval change can
  attach a before/after report instead of an unverified claim — directly closing the gap
  `04-retrieval-design.md` §4 names.
- Eval runs against a dedicated eval workspace/collection scope, not production data, so
  running eval never pollutes real usage and is safe to run repeatedly/in CI.

## Non-goals

- **Not** answer correctness, groundedness, or citation correctness — all three require
  generated answers, which require `packages/generation`, which doesn't exist. Tracked as a
  follow-up once a generation/chat spec ships; this spec's dataset schema should stay
  extensible enough that adding an `expected_answer` field later doesn't require redesigning
  it, but nothing in this spec computes against one.
- **Not** the feedback loop (`07-evaluation-observability.md` §3's "down-voted message
  becomes a new eval case") — that requires real chat messages and `message_feedback` rows,
  neither of which exist yet (no route reads or writes them, confirmed during `030`'s RBAC
  audit). Deferred to whenever a generation/chat phase lands.
- **Not** OpenTelemetry tracing, Prometheus metrics, Grafana dashboards, or Sentry error
  tracking — that's the sibling spec `061-observability-tracing-metrics`.
- **Not** CI integration (a scheduled/automated eval run) — this spec makes the eval CLI
  runnable and its output comparable; wiring it into CI is a small follow-up once this
  exists and the team has a CI pipeline for it to run in (none exists yet in this repo).
- **Not** a change to `packages/retrieval`'s pipeline itself — this spec measures the
  existing dense+sparse+RRF+rerank pipeline (`040`), it doesn't modify it.
- **Not** token/model cost tracking (`07-evaluation-observability.md` §2's cost metric) —
  that's generation-call cost (`messages.usage_json`), which doesn't exist yet either;
  retrieval-side embedding/rerank cost could theoretically be tracked but isn't named as a
  goal here to keep this spec's first increment tight.

## User-facing behavior

No UI yet; this is a developer/CI-facing tool.

- Running the eval CLI against the golden dataset produces a report file
  (`eval/reports/<run_id>.json`) listing per-case results (did the expected source appear in
  the top-K, at what rank, how long the query took) and aggregate recall@k/precision@k/
  latency percentiles.
- Two eval runs with different retrieval configs (e.g. `use_hybrid=false` vs. default) can
  be diffed to see which specific cases regressed or improved — not just an aggregate score
  moving.
- Adding a new golden-dataset case is a plain JSONL append, reviewable in a normal PR diff.

## Acceptance criteria

- [x] A golden dataset file exists with at least one case per content type this repo
      currently indexes (`page_text_plus_ocr`, `table`, `image`), each with a real expected
      source (document/page) verified against an actual ingested fixture.
- [x] The eval CLI runs the full dataset through `packages/retrieval.search` (or its
      constituent legs, per `plan.md`) against a dedicated eval workspace and produces a
      report with recall@k, precision@k, and latency (p50/p95) for the run.
- [x] The report records retrieval config (hybrid on/off, reranker on/off, `k`) and the git
      commit it ran against.
- [x] Running the CLI twice with the same config and dataset produces reports whose
      aggregate metrics match (deterministic enough to trust for comparison — some run-to-run
      variance from LLM-based reranking is expected and should be documented, not hidden).
      Confirmed: two default-config runs (`eval/reports/20260916T135648Z-fbeccea.json`,
      `eval/reports/20260916T135928Z-fbeccea.json`) produced bit-identical recall@k
      (1.0), precision@k (0.125), and mean_reciprocal_rank (0.6156462585034014); only
      latency varied, as expected.
- [x] A documented before/after comparison exists for at least one real question this
      project can already answer: does hybrid (dense+sparse+RRF+rerank) actually outperform
      dense-only on the golden dataset's lexical-heavy cases? (Directly answers
      `04-retrieval-design.md` §4's open "is the reranker earning its latency cost" question
      for the first time with data instead of one hand-checked example.)
      Answer, recorded in `04-retrieval-design.md` §4: on this 7-case dataset, no — both
      configs hit recall@8 = 1.0, but dense-only scored a *higher* MRR (0.929 vs. 0.616)
      and ran ~6x faster (p50 360ms vs. 2172ms). Small sample; worth re-measuring as the
      dataset grows.
- [x] `uv run pytest tests/unit` passes with no live services (dataset loading, metric
      computation, and report-shape logic are unit-testable without a live Qdrant).
      125 passed in 82.74s.
- [x] Running the CLI itself requires the real stack (same as every other live-verified
      phase in this project) — documented, not a blocker to considering the spec done.

## Constraints

- Python 3.12, `uv`-managed, `DocumentPortalException`-style error wrapping
  (`packages/exceptions`).
- Must not modify `packages/retrieval`'s pipeline behavior — eval calls it, it doesn't
  change it.
- Must not touch `packages/retrieval/filters.py::build_workspace_filter` or the isolation
  model — eval runs as an authenticated caller against a real (dedicated eval) workspace,
  using the same auth path every other caller uses, not a bypass.
- Golden dataset cases must reference real, currently-ingestible fixture content — no
  fabricated expected sources that don't correspond to anything actually indexable.
- Local dev/test must stay runnable the way `051` verified it (native Postgres/Keycloak/
  MinIO, Qdrant Cloud, a `--pool=solo` Celery worker on Windows, a real `OPENAI_API_KEY`).

## Open questions

1. **Dataset size and corpus.** `07-evaluation-observability.md` references two prototype
   documents (`data/Client_Contracts_Policies_and_Incident_Records.pdf`,
   `data/llama2-research-paper.pdf`) that don't exist in this repo — only
   `tests/fixtures/sample.pdf` does. Is a golden dataset built entirely against that one
   fixture (already proven rich enough for `040`/`050`/`051`'s hand-checked cases) sufficient
   for this phase's first increment, or should additional fixture documents be added first?
   Leaning: start with `sample.pdf` (it already has real text/table/image content spanning
   many failure modes), expand later. → `plan.md`.
2. **Eval workspace lifecycle.** Does eval re-ingest its fixture(s) into a dedicated
   workspace on every run (simple, always fresh, costs real ingestion time/money per run) or
   ingest once and reuse a persistent eval workspace across runs (faster, but risks drift if
   the fixture or ingestion pipeline changes without re-ingesting)? → `plan.md`.
3. **Recall@k vs. precision@k definition given one expected source per case.** With a single
   `expected_source` per question (not a full relevance-graded set), precision@k is a bit
   degenerate (it's really "did the one relevant chunk appear, divided by k"). Confirm the
   metric definitions `plan.md` will implement match the field's usual meaning closely enough
   to be defensible, or whether recall@k alone (hit/miss in top-K) is the honest metric to
   report given this dataset shape. → `plan.md`.
