# Tasks: Retrieval Evaluation

- **Plan:** [plan.md](plan.md) (approved 2026-09-16)
- **Status:** done

Work top to bottom. Each group should leave the system in a runnable state. Check items off
with `- [x]` as completed; do not delete or renumber finished items.

## Group 1 — Dataset + metrics (pure, no live services)

- [x] Verify `tests/fixtures/sample.pdf` page 13's Q-001–Q-005 table content directly
      (extract text, confirm exact question/expected-source wording) before transcribing it
      into the dataset. — files: none — verify: `pdfplumber` extraction confirmed the exact
      wording; also directly confirmed each answer's real page/table_index via
      `ComplexPDFParser.extract_tables()` rather than trusting the earlier full-PDF-dump
      memory (Q-001/Q-005 → page 5 table_index 1; Q-002 → page 4 text, no table; Q-003 →
      page 6 table_index 1; Q-004 → page 10 table_index 1).
- [x] Add `eval/__init__.py` (empty — makes `eval/` an importable package for unit tests) and
      `eval/dataset.py::EvalCase` (dataclass: `id`, `question`, `expected_filename`,
      `expected_page_number`, `expected_content_type`, `expected_table_index: int | None`,
      `expected_image_index: int | None`) + `load_dataset(path) -> list[EvalCase]` (JSONL
      parse + validation, raising `packages.exceptions.EvalError` — new, added alongside
      this — on a malformed row rather than silently skipping it). — files:
      `eval/__init__.py`, `eval/dataset.py` (new), `packages/exceptions/eval.py` (new),
      `packages/exceptions/__init__.py` (exports `EvalError`),
      `tests/unit/test_eval_dataset.py` (new) — verify: 7 passed (valid parse, optional-
      field defaults, blank-line skipping, missing-field/invalid-JSON/missing-file errors,
      empty-file handling).
- [x] Add `eval/datasets/sample_pdf_retrieval.jsonl`: 7 cases — Q-001–Q-005 (verified real
      page/table_index above), 1 image case reusing `050`'s page-24 portrait query
      (confirmed `image_index=1` via a real parse), 1 additional table case on page 3's
      "Raw Data Inventory" table (genuinely different from Q-001/Q-003/Q-005's tables, for
      real content-type/table diversity — "What format is the ARK-DPA-002 asset?" → "DOCX",
      confirmed against the real extracted table). — files:
      `eval/datasets/sample_pdf_retrieval.jsonl` (new) — verify:
      `load_dataset("eval/datasets/sample_pdf_retrieval.jsonl")` parses all 7 rows without
      error, IDs and questions printed and manually checked.
- [x] Add `eval/metrics.py::hit_at_k(case, results) -> bool`,
      `::reciprocal_rank(case, results) -> float`, `::CaseResult` dataclass,
      `::aggregate(case_results) -> dict` (recall@k = mean hit rate; precision@k = mean of
      hit/k per case, labeled `precision_at_k_note` as degenerate in the report per
      `plan.md`; `mean_reciprocal_rank` included as an informational extra, per `plan.md`'s
      Alternatives — not promoted as a primary metric). Matching uses a structural
      `typing.Protocol`, not an import of `packages.retrieval.dense.SearchResult`, so this
      module has zero `packages/retrieval` dependency and stays trivially unit-testable with
      plain fakes. — files: `eval/metrics.py` (new), `tests/unit/test_eval_metrics.py`
      (new) — verify: 9 passed — hand-computed hit/miss/table-index/image-index matching,
      reciprocal rank at ranks 1/3/never, and a hand-computed 3-case `aggregate()` (caught
      and fixed one bug in the test fixture itself, not the code, during this: a page-number
      mismatch between the image test case and its "correct" result).

## Group 2 — Setup + configurable pipeline (code complete, live-verified in Group 3)

- [x] Add `eval/config.py::Settings` (Keycloak test-user creds — same env vars
      `tests/integration/conftest.py::KeycloakTestSettings` reads —
      `eval_workspace_name: str = "eval"`, `eval_fixture_path: str =
      "tests/fixtures/sample.pdf"`). — files: `eval/config.py` (new),
      `tests/unit/test_eval_config.py` (new) — verify: 1 passed.
- [x] Add `eval/setup.py::mint_token`, `::build_api_client` (in-process ASGI, same pattern
      `tests/integration/conftest.py::api_client` uses — no separate uvicorn process
      needed), `::ensure_eval_workspace(api_client, token, workspace_name) -> str` (list,
      reuse-by-name, or create) and `::ensure_fixture_ingested(api_client, token,
      workspace_id, fixture_path) -> None` (upload — relies on `020`'s content-hash dedup
      for idempotency via the `UploadUnchanged`/`status: "unchanged"` response; polls to
      `ready` only on first upload, own `_poll_job_until_terminal` — not imported from
      `tests/`, since `eval/` is standalone tooling, not test code). — files: `eval/setup.py`
      (new) — verify: no dedicated unit test, per this task's original plan — all of this
      module's real behavior (HTTP calls, Keycloak auth, real ingestion) is only meaningful
      against the live stack; live-verified in Group 3, matching this project's established
      real-dependencies-over-mocks convention.
- [x] Add `eval/pipeline_variants.py::run_search(workspace_id, query, k, *, use_sparse=True,
      use_rerank=True) -> list[SearchResult]` — builds its own Qdrant/OpenAI/FastEmbed
      client instances from `packages/retrieval/config.py::Settings` (not importing
      `packages/retrieval/search.py`'s private cached getters — zero `packages/retrieval`
      changes), calls `dense_search` always, `sparse_search`+`reciprocal_rank_fusion` only
      when `use_sparse`, `rerank` only when `use_rerank` (falls back to returning the
      dense-or-fused list truncated to `k` when rerank is skipped). — files:
      `eval/pipeline_variants.py` (new), `tests/unit/test_eval_pipeline_variants.py` (new)
      — verify: 5 passed (all four legs called by default; sparse+fusion skipped when
      `use_sparse=False`; rerank skipped + truncation when `use_rerank=False`; both off;
      failure wrapping). Caught and fixed one test-fixture bug during this: an `autouse`
      fixture building mocks via lambdas returned a *fresh* `MagicMock()` on every call,
      so an assertion comparing against "the cross encoder instance" never matched the one
      `run_search` actually used — fixed by capturing fixed instances once.

## Group 3 — CLI + live verification

- [x] Add `eval/run.py`: argparse CLI (`--use-sparse/--no-sparse`,
      `--use-rerank/--no-rerank`, `-k`, `--dataset`); bootstraps via `setup.py`; loops the
      dataset calling `pipeline_variants.run_search`, timing each call; writes
      `eval/reports/<run_id>.json` (`run_id` = UTC timestamp + short git commit hash) with
      per-case results, aggregate metrics (`metrics.aggregate`), and the run's config. —
      files: `eval/run.py` (new) — verify: `uv run python -m eval.run --help` shows the
      flags; a real dry run against the live stack is Group 3's next task.
      Fixed a real bug found during the first live run:
      `eval/setup.py::build_api_client` wrapped `apps.api.main.app` in `ASGITransport`
      without ever running the app's startup lifespan, so `app.state.session_factory` was
      never set (`AttributeError: 'State' object has no attribute 'session_factory'` on the
      first DB-touching request). Fixed by setting `app.state.session_factory =
      get_async_sessionmaker()` directly before wrapping, matching
      `tests/integration/conftest.py::api_client`'s existing pattern.
- [x] Run `eval/run.py` against the real stack (default config: hybrid + rerank on) — files:
      none — verify: a real report lands in `eval/reports/`; recall@k for the 7-case dataset
      is inspected manually and looks sane (a fully-broken pipeline would show near-zero
      recall — confirm it doesn't).
      **Result** (`eval/reports/20260916T135648Z-fbeccea.json`): recall@8 = 1.0,
      precision@8 = 0.125 (degenerate, as expected), mean_reciprocal_rank = 0.616,
      latency p50 = 2172ms, p95 = 3610ms. Sane — not near-zero.
- [x] Run `eval/run.py --no-sparse --no-rerank` (dense-only) against the same
      already-ingested eval workspace and compare the two reports — files: none — verify:
      produces the acceptance criterion's required before/after comparison; record the
      actual recall@k numbers for both configs in this task file once run.
      **Result** (`eval/reports/20260916T135709Z-fbeccea.json`): recall@8 = 1.0 (same as
      hybrid+rerank), mean_reciprocal_rank = 0.929 (**higher** than hybrid+rerank's 0.616),
      latency p50 = 360ms, p95 = 1062ms (~6x faster). On this 7-case dataset, dense-only
      ranked the correct result higher on average than the full hybrid+rerank pipeline and
      was substantially faster — a genuine, if small-sample, finding. Recorded in
      `04-retrieval-design.md` §4; the dataset should grow before drawing a firm conclusion
      about disabling the reranker by default.
- [x] Confirm re-running `eval/run.py` a second time doesn't re-ingest (checks for
      `UploadUnchanged` in the setup step's response, not `UploadAccepted`) — files: none —
      verify: second run's setup phase completes near-instantly compared to the first.
      Confirmed directly: re-POSTing the fixture to `/workspaces/{id}/documents` returned
      `200 {"status": "unchanged", ...}` — no new ingestion job created.
- [x] `uv run pytest tests/unit` passes with no live services. — files: none — verify:
      record pass count here once run.
      **Result:** 125 passed in 82.74s.
- [x] Update `07-evaluation-observability.md` §2 and `04-retrieval-design.md` §4 per
      `plan.md`'s Architecture doc deltas. — files:
      `specs/architecture/07-evaluation-observability.md`,
      `specs/architecture/04-retrieval-design.md`.
- [x] `specs/README.md` gains a `060` row; status set to `done`.

## Verification (end of increment)

- [x] All `spec.md` acceptance criteria satisfied, including the before/after hybrid-vs-
      dense-only comparison with real numbers recorded.
- [x] `uv run pytest tests/unit` passes with no live services.
- [x] `eval/run.py` runs successfully against the real stack, producing comparable reports.
- [x] `07-evaluation-observability.md`, `04-retrieval-design.md` updated per `plan.md`'s
      Architecture doc deltas.
- [x] `specs/README.md` gains a `060` row; status set to `done`.
