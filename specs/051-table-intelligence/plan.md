# Plan: Table Intelligence

- **Spec:** [spec.md](spec.md) (approved 2026-09-15)
- **Status:** draft

## Summary

Two new Postgres tables (`document_tables`, `table_cells`) hold table metadata and
normalized rows, both RLS-protected with the exact one-hop `EXISTS`-join-through-`documents`
policy shape `030`'s migration `0002` already established for `document_versions`/
`ingestion_jobs` — no new isolation pattern, just applying the existing one to two more
document-derived tables. Raw table content (CSV) moves to object storage, mirroring
`packages/storage/keys.py::image_key`'s existing per-document-version key pattern. An LLM
call produces a natural-language summary that becomes the primary embedded text (same
"caption replaces raw dump" move `050` makes for images); column types are inferred
locally via pandas, no second LLM call. Tables above a row-count threshold get split into
row-group Qdrant chunks, each repeating the header row.

## Architecture doc deltas

| Doc | Change |
|---|---|
| `05-multimodal-strategy.md` | §2: mark the baseline table-intelligence improvement as implemented; note the concrete schema (`document_tables`/`table_cells`, not the doc's placeholder `table_cells`-only naming) and that column-type inference is heuristic (pandas), not LLM-assisted. |
| `02-data-model.md` | §0 (as-built schema): add `document_tables` and `table_cells` to the live entity list and their RLS coverage, alongside the existing five RLS-protected tables from `030`. |
| `03-ingestion-workflow.md` | §3 (`parsing` stage): note table summarization/row-group chunking now happens here, alongside vision captioning (`050`). |

## Component/module ownership

- **`packages/db/models.py`** — two new SQLAlchemy models:
  - `DocumentTable`: `id` (uuid pk), `document_id` (fk `documents`, not null),
    `document_version_id` (fk `document_versions`, not null), `table_index` (int),
    `page_number` (int), `object_storage_key` (str — raw CSV location), `summary` (text —
    the LLM summary, same text embedded in Qdrant), `schema_json` (JSONB — `[{"name":
    "...", "type": "string|number|date|currency"}]`), `row_count` (int), `created_at`.
  - `TableCell`: `id` (uuid pk), `table_id` (fk `document_tables`, cascade delete),
    `document_id` (fk `documents`, not null — a direct FK, not a denormalized copy of
    `workspace_id`; keeps the RLS policy a one-hop join like every other `030`-protected
    table instead of a two-hop `table_cells -> document_tables -> documents` join),
    `row_index` (int), `column_name` (str), `value` (text — kept as text at this baseline;
    the `schema_json` type is what a future consumer would use to coerce it), `created_at`.
    Unique on `(table_id, row_index, column_name)`.
- **`packages/db/migrations/versions/0003_table_intelligence.py`** (new) — creates both
  tables (with indexes on `document_id`, `document_version_id`) and, in the same migration
  (these are brand new tables, no reason to defer RLS the way `030` had to retrofit it onto
  pre-existing ones), `ENABLE`/`FORCE ROW LEVEL SECURITY` + a policy on each: `document_tables`
  via `EXISTS (... documents d WHERE d.id = document_tables.document_id AND d.workspace_id =
  current_setting(...)::uuid)`, `table_cells` via the same shape keyed on its own direct
  `document_id` column.
- **`packages/storage/keys.py`** — new `table_key(workspace_id, document_id,
  document_version_id, table_index) -> str`, mirroring `image_key`'s exact shape:
  `f"{workspace_id}/{document_id}/{document_version_id}/tables/{table_index}.csv"`.
- **`packages/ingestion/config.py`** — new settings: `table_chunk_row_threshold: int = 20`
  (tables at or below this many rows stay one chunk), `table_chunk_group_size: int = 15`
  (row-group size once split).
- **`packages/ingestion/table_intelligence.py`** (new) — three focused, independently unit-
  testable functions, mirroring `050`'s `vision.py` isolation pattern:
  - `summarize_table(chat_model: ChatOpenAI, markdown: str) -> str | None` — one LLM call
    per table, same degrade-to-`None`-on-failure contract as `050`'s `caption_image`. On
    `None`, that table's embedded text falls back to today's raw-markdown behavior (same
    "degrade gracefully" philosophy as everywhere else in this pipeline) rather than
    failing the job.
  - `infer_column_types(dataframe: pd.DataFrame) -> list[dict]` — pure, local, no LLM:
    tries `pd.to_numeric`/`pd.to_datetime` per column, checks for `$`/`%` affixes for
    currency, falls back to `"string"`. Returns `[{"name": ..., "type": ...}, ...]`.
  - `chunk_table_by_rows(dataframe: pd.DataFrame, threshold: int, group_size: int) ->
    list[pd.DataFrame]` — returns `[dataframe]` unchanged at or below `threshold`, otherwise
    splits into `group_size`-row groups (last group may be smaller), header implicitly
    preserved since each group is still a full `DataFrame` with the same columns.
- **`packages/ingestion/pipeline.py::run_ingestion`** — gains a `chat_model: ChatOpenAI`
  parameter (shared with `050`'s vision captioning — one `ChatOpenAI` instance serves both
  concerns; `gpt-4.1-mini` handles table summarization too, no separate model needed). For
  each parsed table: uploads the raw CSV to object storage (`table_key`), inserts one
  `DocumentTable` row (summary, schema, row count) and one `TableCell` row per cell, then
  replaces the table's LangChain `Document`(s) — one per row-group from
  `chunk_table_by_rows` — with summary-primary embedded text (`"TABLE ON PAGE {page},
  TABLE {index} (part {n} of {total}):\n\nSUMMARY:\n{summary}\n\nHEADER: {columns}\n\nROWS:
  \n{row_group_markdown}"`), each carrying `table_id` in its metadata so the Qdrant payload
  can reference back to `document_tables` if ever needed.
- **`workers/celery_app.py`** — already constructs `ChatOpenAI` per task (per `050`'s plan)
  and passes it into `run_ingestion` as `chat_model`; that same instance now serves both
  captioning and table summarization, no second client needed.

## Data model changes

- **Postgres**: two new tables (`document_tables`, `table_cells`), migration `0003`, both
  RLS-protected from creation — see Component ownership. No changes to existing tables.
- **Object storage**: new `.../tables/{table_index}.csv` keys per document version, mirroring
  the existing `.../images/{index}.png` pattern.
- **Qdrant payload**: table points gain `table_id` (uuid, references `document_tables.id`)
  and `row_group_index`/`row_group_count` (ints, for a chunk to know its position within a
  split table) — additive, no payload index needed (not filter fields), no collection
  recreation needed (payload-only change, unlike `040`'s vector schema change).

## API contract

No changes. `POST /workspaces/{workspace_id}/search` is untouched — this phase only changes
what text/rows get produced for table chunks and what's queryable directly in Postgres
(which nothing queries yet, per spec's non-goals).

## Retrieval / ingestion impact

- **Ingestion**: one LLM call per table (summary) — same cost profile as `050`'s one call per
  image; plus local (no-LLM) column-type inference and CSV upload, both cheap. A large table
  now produces multiple Qdrant points (row-groups) instead of one oversized point — more
  points overall, each individually more retrievable.
- **Retrieval**: none directly — `packages/retrieval` is untouched. Row-group chunking does
  mean a query might now match one row-group of a large table rather than needing to match
  an entire oversized blob, which should improve (not measured here) retrieval precision for
  large tables specifically.

## Security / tenancy impact

This is the one part of Phase 6 that **does** touch the tenancy-adjacent surface area (new
Postgres tables), so it gets the same scrutiny `030`'s migration did:

- Both new tables are RLS-protected identically in shape to `030`'s existing pattern —
  `FORCE ROW LEVEL SECURITY`, keyed on the same `app.current_workspace_id` GUC, set by the
  same `apps/api/deps/rbac.py::require_workspace_role` / `packages/db/rls.py::
  set_workspace_scope_sync` call sites already in place. No new GUC, no new scoping
  mechanism — these tables simply join the set of tables `030`'s existing scope-setting
  covers.
- `packages/ingestion/pipeline.py::run_ingestion` already calls
  `set_workspace_scope_sync(session, workspace_id)` as its first action (from `030`) —
  since these new tables are written within the same `run_ingestion` transaction, no new
  scoping call site is needed; the existing one now also covers `document_tables`/
  `table_cells` writes.
- `tests/integration/test_rls.py`'s pattern is extended (not replaced) to add both new
  tables to its cross-workspace-isolation assertions, proving this at the same
  independent-of-the-app level `030` already established.
- No change to `build_workspace_filter`, the search route, or Qdrant isolation — this spec's
  isolation surface is entirely on the Postgres side.

## Rollout

Big-bang, no flag:
- New tables, RLS-protected from their first migration — no retrofit risk like `030` faced
  with pre-existing tables.
- Revert path: `alembic downgrade` drops both new tables and their policies cleanly (nothing
  else references them yet); the ingestion pipeline reverts to markdown-only table chunks
  with no row-group splitting if the corresponding pipeline code is also reverted.
- No production data to migrate (new tables, `012`'s established norm).

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `run_ingestion`'s per-table Postgres writes (one `DocumentTable` + N `TableCell` rows) add real transaction time for large tables | Medium for genuinely large tables | Low — ingestion is already async and tolerant of multi-minute runs | Bulk-insert `TableCell` rows in one `session.add_all(...)` rather than row-by-row `session.add()` + flush |
| Column-type inference misclassifies ambiguous columns (e.g. a numeric-looking ID column classified as `number`) | Medium — heuristic, not ground truth | Low — `schema_json` is metadata for a future consumer, nothing depends on its correctness yet (no query tool built) | Accepted; a future text-to-SQL spec (explicitly deferred) is where getting this right actually matters, and can revisit the approach then |
| Table summarization failure degrades to header+rows only (no `SUMMARY` section) as embedded text — see Deviations, this is milder than originally planned, not the full raw-markdown fallback | Low | Low — same class of degrade-gracefully tradeoff `050` accepts for captioning | Accepted, consistent with this pipeline's established "one bad item never fails the whole job" philosophy |
| Two new RLS-protected tables written in the same transaction as everything else `run_ingestion` already writes — a mistake in the new INSERT logic could violate `WITH CHECK` and fail the whole job load-bearing on GUC state set correctly | Low — same GUC/scope call already covers it, no new call site | Medium if it happens (job fails at the new step) | Covered by extending `tests/integration/test_rls.py` and by the existing full-suite regression run before calling this phase done |

## Deviations found during implementation

- **Point-ID collision across a table's row-groups — found during code review, before any
  test ran.** `_point_id`'s identity is `(document_version_id, page_number, content_type,
  table_index, image_index, chunk_index)`. Splitting a table's LangChain `Document`s into
  multiple row-group documents *before* the existing chunking loop means each row-group
  individually passes through `_split()` as a single-item, un-split list — `chunk_index`
  resets to `0` for every one of them. Without a fix, a 3-row-group table would compute the
  *same* point ID for all 3 groups, and each upsert would silently overwrite the last one —
  only the final row-group's chunk would actually end up in Qdrant. Fixed: when
  `row_group_index` is present in a chunk's metadata, it's folded into the `table_index`
  value passed to `_point_id` (`f"{table_index}-{row_group_index}"`), disambiguating each
  group. Every other content type's point-ID computation is untouched (`row_group_index` is
  simply absent from their metadata).
- **Summarization-failure fallback is milder than planned.** The plan's Component ownership
  section described falling back to raw markdown as embedded text when `summarize_table`
  returns `None`. Implementation instead omits only the `SUMMARY:` section and keeps the
  per-row-group `HEADER:`/`ROWS:` text — the row-group's own content is already
  self-sufficient (that's the point of row-group chunking), so there was no need to fall all
  the way back to the *entire* table's raw markdown, which would have reintroduced the
  oversized-chunk problem this spec exists to fix, just for tables where summarization
  happens to fail.

## Alternatives considered

- **DuckDB over stored CSV** instead of a Postgres `table_cells` table (the doc's other
  suggested option) — rejected: adds a new engine/dependency for a table this small at
  current scale; Postgres already has the RLS pattern to reuse and no code queries this data
  yet, so there's no performance case for DuckDB today. Revisit if a future text-to-SQL spec
  needs OLAP-style query performance over large tables.
- **LLM-assisted column type inference** instead of pandas heuristics — rejected: this phase
  already adds one LLM call per table (the summary); a second call for schema inference is
  avoidable cost for metadata nothing currently queries. Revisit alongside the deferred
  text-to-SQL spec if heuristic inference proves too weak in practice.
- **Denormalizing `workspace_id` directly onto `document_tables`/`table_cells`** (the old
  multi-tenant `tenant_id` pattern `02-data-model.md` §2 describes) instead of a join through
  `documents` — rejected for the same reason `030` rejected it for `document_versions`/
  `ingestion_jobs`: performance isn't a concern yet, and avoiding the denormalization-sync
  burden is worth a one-hop join at this scale.
- **A single `tables` table with `schema_json` cell data embedded as JSONB** instead of a
  separate `table_cells` row-per-cell table — rejected: the architecture doc explicitly
  specifies `(document_id, table_index, row_index, column_name)` as a normalized key, which
  reads as row-per-cell; a future text-to-SQL tool would need to run real `WHERE`/aggregate
  queries against normalized rows, which a JSONB blob would make much harder without first
  unnesting it.
