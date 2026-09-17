# Plan: Retrieval Evaluation

- **Spec:** [spec.md](spec.md) (approved 2026-09-15)
- **Status:** done

## Summary

A new top-level `eval/` package (config, dataset loading, metrics, a setup/bootstrap module,
and the CLI itself) that authenticates as a real user (reusing the same Keycloak Resource
Owner Password Credentials flow `tests/integration/conftest.py` already uses), finds-or-
creates a dedicated "eval" workspace via the real `apps/api` routes (in-process ASGI, no
separate server process needed — same pattern `tests/integration/conftest.py::api_client`
uses), idempotently uploads the golden dataset's fixture PDF (upload is already
content-hash-deduped from `020`, so re-running eval doesn't re-ingest or re-pay LLM
captioning/summarization costs unless the fixture actually changed), then runs each golden
case through `packages/retrieval`'s public building blocks directly — not through
`packages.retrieval.search.search()`, and not by modifying it (per the spec's constraint) —
so different legs can be toggled on/off for comparison without touching production retrieval
code at all.

The golden dataset's first five cases come directly from `tests/fixtures/sample.pdf` page
13's own built-in "Evaluation Dataset" section — the fixture already ships five
question/expected-source/expected-answer-element rows (Q-001 through Q-005) clearly designed
for exactly this purpose. Reusing them (retrieval-relevant fields only — no `expected_answer`
usage yet, per the spec's non-goal) means the dataset starts from real, already-present
content rather than invented cases.

## Architecture doc deltas

| Doc | Change |
|---|---|
| `07-evaluation-observability.md` | §2: mark the golden-dataset/eval-CLI/recall-precision-latency portion as implemented, retrieval-only; note answer correctness/groundedness/citation correctness/cost remain deferred pending a generation pipeline (this spec's own non-goal, now recorded here too so the doc doesn't imply they already exist). |
| `04-retrieval-design.md` | §4: replace the "should be able to measure this pipeline with and without the reranker" aspiration with a pointer to `060-retrieval-evaluation` and its first before/after report. |

## Component/module ownership

- **`eval/config.py`** (new) — `Settings`: Keycloak test-user creds (same env vars
  `tests/integration/conftest.py::KeycloakTestSettings` already reads —
  `keycloak_test_client_id/secret`, `keycloak_test_username/password` — reused rather than
  provisioning a separate eval service account, since these already exist and work),
  `eval_workspace_name: str = "eval"`, `eval_fixture_path: str =
  "tests/fixtures/sample.pdf"`.
- **`eval/dataset.py`** (new) — `EvalCase` dataclass: `id`, `question`,
  `expected_filename`, `expected_page_number`, `expected_content_type`,
  `expected_table_index: int | None`, `expected_image_index: int | None` (matched against
  `SearchResultOut`'s existing fields — `filename`/`page_number`/`content_type`/
  `table_index`/`image_index` — no new fields needed anywhere in `packages/retrieval` or
  `apps/api`, since a search result already carries everything needed to check a hit).
  `load_dataset(path) -> list[EvalCase]` parses and validates the JSONL.
- **`eval/datasets/sample_pdf_retrieval.jsonl`** (new) — the golden dataset. First 5 cases
  ported from `sample.pdf` page 13's own Q-001–Q-005 (retrieval-relevant fields only);
  1 image case reusing `050`'s already-verified page-24 portrait query; 1 additional table
  case (a different table than Q-003's) for coverage — 7 cases total for this first
  increment, covering all three content types.
- **`eval/metrics.py`** (new) — `hit_at_k(case, results) -> bool` (did a result matching
  `expected_*` appear anywhere in the returned top-k), `reciprocal_rank(case, results) ->
  float` (informational — see Alternatives), `aggregate(per_case_results) -> dict`
  (recall@k = mean hit rate; precision@k = hit@k / k per case, averaged — implemented as
  specified, with the report explicitly labeling it as degenerate for a
  single-relevant-item dataset, resolving Open Question 3 by being honest in the report
  rather than hiding the shape).
- **`eval/setup.py`** (new) — `ensure_eval_workspace(api_client, token) -> str`
  (workspace_id): calls `GET /workspaces`, returns the first one named
  `settings.eval_workspace_name` if found, else `POST /workspaces` to create it. `
  ensure_fixture_ingested(api_client, token, workspace_id) -> None`: uploads
  `eval_fixture_path`; relies on `020`'s existing content-hash dedup (`UploadUnchanged`
  response) to make re-runs a no-op; polls to `ready` on first upload only.
- **`eval/pipeline_variants.py`** (new) — `run_search(workspace_id, query, k, *, use_sparse:
  bool = True, use_rerank: bool = True) -> list[SearchResult]`. Builds its own
  `QdrantClient`/`OpenAIEmbeddings`/`SparseTextEmbedding`/`TextCrossEncoder` instances from
  `packages/retrieval/config.py::Settings` (already public) rather than importing
  `packages/retrieval/search.py`'s private, underscore-prefixed cached getters — zero lines
  of `packages/retrieval` touched, fully honoring the spec's "must not modify
  `packages/retrieval`'s pipeline behavior" constraint. Calls the same public functions
  production code calls (`dense_search`, `sparse_search`, `reciprocal_rank_fusion`,
  `rerank`) — this is composition, not reimplementation — just with `use_sparse`/
  `use_rerank` choosing which legs run, a variability production `search()` never needs
  (it always wants the best pipeline) and eval specifically does.
- **`eval/run.py`** (new) — the CLI: parses `--use-sparse/--no-sparse`,
  `--use-rerank/--no-rerank`, `-k`, `--dataset` flags; calls `setup.py` to bootstrap; loops
  the dataset calling `pipeline_variants.run_search` per case, timing each call; writes
  `eval/reports/<run_id>.json` (`run_id` = UTC timestamp + short git commit hash).

## Data model changes

None. No Postgres/Qdrant schema changes — eval reads through the exact same tables/
collection every other phase already writes to, via the existing `apps/api` upload route and
`packages/retrieval`'s existing public functions.

## API contract

None. Eval calls existing `apps/api` routes (`POST /workspaces`, `GET /workspaces`,
`POST /workspaces/{id}/documents`, `GET /workspaces/{id}/jobs/{id}`) exactly as any other
authenticated client would — no new routes, no changes to existing ones.

## Retrieval / ingestion impact

- **Retrieval**: `eval/pipeline_variants.py` exercises the same dense/sparse/fusion/rerank
  functions production `search()` calls — no behavior change to the production pipeline.
- **Ingestion**: none beyond one real (idempotent) upload of the fixture PDF, exactly the
  same as any other document upload — no ingestion code changes.
- This is precisely the measurement `04-retrieval-design.md` §4 said was missing: the first
  real recall@k comparison between dense-only and the full hybrid+rerank pipeline, replacing
  "we upgraded to hybrid retrieval" with a number.

## Security / tenancy impact

None on the isolation model itself, but worth being explicit since this is a new caller of
the retrieval/ingestion path:

- Eval authenticates as a real user via the real Keycloak flow and operates within a real,
  ordinarily-authorized workspace (`require_workspace_role`-gated like any other caller) —
  it is not a bypass or a privileged internal path.
- `eval/pipeline_variants.py` still calls `packages/retrieval/filters.py::build_workspace_filter`
  (via `dense_search`/`sparse_search`, unchanged) for every query — the mandatory workspace
  filter applies to eval traffic exactly as it does to production traffic.
- The eval workspace is just a normal workspace scoped to whichever user's credentials run
  eval — no new data ever crosses a workspace boundary that the existing RBAC/RLS model
  doesn't already enforce.

## Rollout

Big-bang, no flag:
- Purely additive — a new top-level `eval/` package and dataset/report files. No production
  code path changes.
- First run against a fresh environment creates the eval workspace and ingests the fixture
  (real cost: one document's worth of embedding + vision captioning + table summarization,
  a few dollars of API calls at most); every subsequent run reuses both via the existing
  idempotency the platform already has.
- Revert path: delete `eval/` — nothing else in the codebase depends on it.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Report-to-report variance from LLM-based reranking makes "deterministic enough to trust" (an acceptance criterion) hard to satisfy exactly | Medium — cross-encoder scoring is deterministic given fixed weights, but network/API-level nondeterminism (retries, minor float differences) is possible | Low — affects report precision, not correctness of the tool | Document expected variance explicitly in the report/README rather than asserting byte-identical reports across runs |
| `eval/pipeline_variants.py` duplicating client-construction code that already exists in `packages/retrieval/search.py` (as private helpers) | Low impact, but a real, acknowledged duplication | Low — a handful of lines, and the alternative (exposing internals for reuse) would touch `packages/retrieval` itself, which the spec's constraint discourages | Accepted; revisit if a third caller needs the same client-construction logic, which would be the point where extracting a shared, explicitly-public factory becomes worth the `packages/retrieval` change |
| The eval workspace accumulates stale points if the fixture PDF or ingestion pipeline changes without a corresponding re-ingest (content-hash dedup means an unchanged file never triggers reprocessing, but a *pipeline* change with the same file also produces no new upload) | Medium over time as `packages/ingestion` evolves | Medium — a report could reflect a stale index | Document that `eval/setup.py`'s dedup checks file content only, not pipeline version; a deliberate re-ingest (delete-and-reupload, or a future `--force-reingest` flag) is needed after a pipeline change — not solved automatically in this first increment |

## Alternatives considered

- **Adding `use_sparse`/`use_rerank` toggle parameters directly to
  `packages.retrieval.search.search()`** — considered, rejected in favor of
  `eval/pipeline_variants.py` composing the same public functions itself: the spec's own
  constraint says eval must not change `packages/retrieval`'s pipeline behavior, and
  production `search()` has no legitimate use for these toggles (it always wants the best
  pipeline) — adding them there would be dead optionality outside of eval.
- **Mean Reciprocal Rank as a primary metric** instead of (or alongside) recall@k/
  precision@k — MRR is arguably a better fit for a single-relevant-item dataset than
  precision@k. Included as an informational field (`reciprocal_rank`) per case, but not
  promoted to a primary aggregate metric in this increment, since the spec's Goals commit
  specifically to recall@k/precision@k and expanding metric scope mid-plan is exactly the
  kind of drift `spec.md` being frozen is meant to prevent — revisit in a follow-up if
  precision@k's degenerate shape proves unsatisfying in practice.
- **A dedicated eval-only Keycloak service account** instead of reusing the test user
  credentials — rejected for this first increment: it's one more piece of infrastructure to
  provision for a dev/CI tool that doesn't need its own identity distinct from what tests
  already use; revisit if eval needs to run somewhere the test realm/user isn't available
  (e.g. a real CI environment with its own Keycloak).
