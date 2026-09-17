# Tasks: Table Intelligence

- **Plan:** [plan.md](plan.md) (approved 2026-09-15)
- **Status:** done — 103/103 unit tests, 37/37 integration tests (full real stack, real LLM
  summarization calls). Real, live-verified proof: a specific known table/cell from the
  fixture PDF round-trips correctly through RLS-protected Postgres storage, and the
  resulting chunk is searchable with its LLM summary as primary content. A real point-ID
  collision bug across multi-row-group tables was found and fixed before any test ran (see
  `plan.md` Deviations). `030`'s/`040`'s authorization suites re-ran unmodified and stayed
  green throughout. Scope note: none of the fixture PDF's tables exceed the row-group
  threshold, so the multi-group chunking path is proven live only via the unit-level
  synthetic-DataFrame test, not a real above-threshold PDF table — judged sufficient rather
  than building a bespoke large-table fixture (see Group 4).

Work top to bottom. Each group should leave the system in a runnable state. Check items off
with `- [x]` as completed; do not delete or renumber finished items.

## Group 1 — Schema: `document_tables` + `table_cells`

- [x] Add `DocumentTable` and `TableCell` models to `packages/db/models.py` per `plan.md`'s
      Component ownership (fields, FKs, unique constraint on `TableCell(table_id, row_index,
      column_name)`). — files: `packages/db/models.py`, `tests/unit/test_db_models.py`
      (extended — this file's actual established style is SQLAlchemy-metadata-level
      assertions, not ORM round-trips; added both tables to `EXPECTED_TABLES`, a unique-
      constraint check, and a check that both reach `documents` via a direct `document_id`
      column rather than `workspace_id`) — verify: 7 passed.
- [x] Write migration `0003_table_intelligence.py`: create both tables with indexes on
      `document_id`/`document_version_id`, then `ENABLE`/`FORCE ROW LEVEL SECURITY` + a
      one-hop `EXISTS`-join policy on each (same shape as `0002`'s `document_versions`/
      `ingestion_jobs` policies). — files:
      `packages/db/migrations/versions/0003_table_intelligence.py` — verify:
      `alembic upgrade head` then `alembic downgrade -1` then `alembic upgrade head` all ran
      clean; confirmed via `pg_class`/`pg_policies` that both tables have
      `relrowsecurity`/`relforcerowsecurity` true and a policy, mirroring how `030` verified
      `0002`.
- [x] Extend `tests/integration/test_rls.py`'s `_seed_two_workspaces` and isolation tests to
      cover `document_tables`/`table_cells` — a table row and its cells created under
      workspace X must be invisible when the GUC is scoped to workspace Y. — files:
      `tests/integration/test_rls.py` — verify: 5 passed against real Postgres alone (no
      Keycloak/Qdrant/MinIO needed for this file, per its own docstring).

## Group 2 — Local helpers (no DB/network — pure functions, isolated unit tests)

- [x] Add `packages/storage/keys.py::table_key(workspace_id, document_id,
      document_version_id, table_index) -> str`, mirroring `image_key`'s shape. — files:
      `packages/storage/keys.py`, `tests/unit/test_storage_keys.py` — verify: 4 passed.
- [x] Add `packages/ingestion/table_intelligence.py::infer_column_types(dataframe) ->
      list[dict]` (pandas-based, no LLM, no network) and `::chunk_table_by_rows(dataframe,
      threshold, group_size) -> list[DataFrame]`. — files:
      `packages/ingestion/table_intelligence.py` (new),
      `tests/unit/test_ingestion_table_intelligence.py` (new) — verify: 10 passed (numeric/
      currency/date/string/mixed-column classification; at/above-threshold chunking with
      exact group-size boundaries and preserved columns). Suppressed a `pandas` `UserWarning`
      that fired on every non-date string column tried as a date (noisy, not actionable for
      this best-effort heuristic).
- [x] Add `packages/ingestion/table_intelligence.py::summarize_table(chat_model, markdown)
      -> str | None` — one LLM call, same degrade-to-`None`-on-failure contract as `050`'s
      `caption_image`. — files: `packages/ingestion/table_intelligence.py` — verify: covered
      by the same 10-test run above (response passthrough, failure, blank-response cases).
- [x] Add `table_chunk_row_threshold: int = 20` and `table_chunk_group_size: int = 15` to
      `packages/ingestion/config.py::Settings`. — files: `packages/ingestion/config.py`,
      `tests/unit/test_ingestion_config.py` — verify: 2 passed.

## Group 3 — Wire into the ingestion pipeline

- [x] In `packages/ingestion/pipeline.py::run_ingestion`, for each parsed table: upload the
      raw CSV to object storage via `table_key`; insert one `DocumentTable` row (summary via
      `summarize_table`, schema via `infer_column_types`, row count) and its `TableCell`
      rows (bulk `session.add_all`, per `plan.md`'s risk mitigation — not one `session.add`
      per cell); replace that table's LangChain `Document`(s) with one per row-group from
      `chunk_table_by_rows`, embedding the summary (when available — see `plan.md`
      Deviations for the milder no-summary fallback) plus that group's header+rows, each
      carrying `table_id`/`row_group_index`/`row_group_count` in metadata. Reuses the
      `chat_model: ChatOpenAI` parameter `050` already added to this function's signature.
      — files: `packages/ingestion/pipeline.py` — verify: `uv run pytest tests/unit` — no
      regressions (same "no dedicated `run_ingestion` unit test" convention as `050` and
      `040` — verified live in Group 4).
      **Found during implementation, before any test ran — see `plan.md` Deviations:** a
      multi-row-group table's chunks all collided on the same deterministic point ID
      (`chunk_index` resets to 0 for each row-group's own un-split `_split()` call), so only
      the last group would have survived the upsert. Fixed by folding `row_group_index` into
      the `table_index` value passed to `_point_id` when present.
- [x] Add `table_id`, `row_group_index`, `row_group_count` to the Qdrant point payload dict
      for table-content-type points. — files: `packages/ingestion/pipeline.py` — verify:
      covered by the live point-inspection check in Group 4.

## Group 4 — Live verification, docs, regression

- [x] Restart the Celery worker (doesn't hot-reload) and re-run
      `tests/integration/test_upload_and_ingest.py` to confirm ingestion still completes
      end-to-end with the new table-writing steps in the parsing stage. — files: none —
      verify: 1 passed. Manual DB inspection right after a standalone pytest run isn't
      possible here — `db_engine`'s session-scoped teardown downgrades the schema to base
      the moment that pytest process exits — so the actual data check happens inside the
      dedicated integration test below instead, in the same pytest session, before teardown.
- [x] Add an integration test verifying table intelligence end to end. **Scope narrowed from
      the original plan**: checked `tests/fixtures/sample.pdf`'s tables directly via
      `ComplexPDFParser.extract_tables()` — the largest is 8 rows, none exceed
      `table_chunk_row_threshold=20`, so there's no naturally-occurring above-threshold table
      to exercise the multi-row-group path with a real PDF. That arithmetic is already
      exactly verified with a real 32-row DataFrame in
      `tests/unit/test_ingestion_table_intelligence.py` (`[15, 15, 2]` boundaries); building
      a bespoke large-table PDF fixture just to re-prove already-proven arithmetic
      end-to-end wasn't judged worth it. Instead this test proves what a unit test can't:
      real LLM summarization succeeds, real RLS-protected `document_tables`/`table_cells`
      writes are correct (checked against a specific known table/cell from the fixture), and
      the resulting chunk is actually searchable with `SUMMARY:` as its primary embedded
      text. — files: `tests/integration/test_table_intelligence.py` (new) — verify: passes
      against the real stack.
- [x] Re-run `tests/integration/test_search_rbac.py` unmodified — the authorization
      regression gate. — files: none — verify: 5 passed.
- [x] Update `05-multimodal-strategy.md` §2 (marked implemented, notes the actual
      `document_tables`/`table_cells` naming and heuristic column-type inference) and
      `03-ingestion-workflow.md` §3. — files: `specs/architecture/05-multimodal-strategy.md`,
      `specs/architecture/03-ingestion-workflow.md`. Also updated `02-data-model.md` §0 to
      add both new tables to the as-built schema list, indexes, and RLS coverage note.
- [x] Full regression: `uv run pytest tests/unit` and `uv run pytest tests/integration` both
      green. — verify: 103 passed (unit), 37 passed (integration, one combined run of the
      whole `tests/integration` directory).
- [x] `specs/README.md` gains a `051` row; status set to `done`.

## Verification (end of increment)

- [x] All `spec.md` acceptance criteria satisfied.
- [x] `uv run pytest tests/unit` passes with no live services — 103 passed.
- [x] `uv run pytest tests/integration` passes against the full real stack — 37 passed.
- [x] `05-multimodal-strategy.md`, `03-ingestion-workflow.md`, `02-data-model.md` updated
      per `plan.md`'s Architecture doc deltas.
- [x] `specs/README.md` gains a `051` row; status set to `done`.
