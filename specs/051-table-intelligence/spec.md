# Spec: Table Intelligence

- **ID:** `051-table-intelligence`
- **Roadmap phase:** [08-roadmap.md](../architecture/08-roadmap.md) Phase 6 — Better
  Multimodal Retrieval (`050-059`), the tables half —
  [`05-multimodal-strategy.md`](../architecture/05-multimodal-strategy.md) §2. Sibling to
  `050-vision-captioning` (images) — split out because this is an independently-sized
  increment: it needs its own new Postgres table and migration, which `050` does not.
- **Status:** draft
- **Owner:** Saravanan Shanmugam
- **Date:** 2026-09-15

## Problem statement

`packages/parsing/pdf_parser.py::ComplexPDFParser.extract_tables` (pdfplumber) already
produces `raw_table` (list of lists), a pandas-rendered `markdown`, and a `csv` string per
table — but only the **markdown** ends up as the embedded/searchable text
(`create_langchain_documents`'s table branch). This is weak in two concrete ways
`05-multimodal-strategy.md` §2 names:

1. Tables are explicitly *not* chunked by `packages/ingestion/pipeline.py::_split` (only
   `page_text_plus_ocr` content is split) — a large table becomes one oversized,
   mostly-unsearchable chunk, and markdown itself is a weak retrieval surface even at a
   reasonable size (long tables blow past useful embedding granularity).
2. There is no way to answer an exact factual lookup ("what was the amount in row 14",
   "what was the Q3 total") from a markdown-embedding similarity search — that structurally
   requires matching a *number*, not a *meaning*.

## Goals

Per `05-multimodal-strategy.md` §2's four-part baseline (items 1-3 change what's produced at
ingestion time; item 4 is storage only, not querying — see Non-goals):

1. **Persist raw table content** (`raw_table`, `csv`) durably — today it only exists in the
   worker-local, debug-only `table_records.json` (`save_outputs`, off by default) and is
   otherwise discarded once the job finishes.
2. **LLM-generated searchable summary** becomes the **primary embedded text** for a table's
   chunk(s), replacing raw markdown as the dense/sparse embedding source — same rationale as
   `050`'s image captions: a natural-language description of what the table contains is a
   better retrieval surface than a markdown dump. Markdown/raw content stays available
   alongside it (payload and/or the persisted table, per Goal 1) for citation and generation
   time, just not as the primary embedded signal.
3. **Headers/schema metadata** — column names and inferred types (string/number/date/
   currency) — stored as structured metadata alongside the chunk, so a future generation
   prompt or filter can reference "column X" reliably instead of re-parsing markdown.
4. **Normalized structured rows** — the cleaned table loaded into a queryable form keyed by
   `(document_id, table_index, row_index, column_name)` — stored as part of this phase, but
   **not queried** by anything yet (see Non-goals; the query tool is a future spec).
5. **Row-group chunking**: tables above a size threshold are split by row-groups (not the
   character-based `RecursiveCharacterTextSplitter`, which would cut a row in half), with the
   header row repeated in every chunk so no chunk loses column context.
6. Any new Postgres table this introduces follows the workspace-isolation pattern
   `030-workspace-rbac-filtering` already established for every other document-derived
   table: reachable from `workspace_id` (directly or via a join, like `document_versions`/
   `ingestion_jobs`) and covered by the same workspace-scoped Row-Level Security migration
   pattern — this is not optional or deferred, it's the same category of table `030`'s RLS
   already protects.

## Non-goals

- **Not** a text-to-SQL / text-to-pandas answer tool over the normalized rows —
  `05-multimodal-strategy.md` §2 explicitly marks this "Advanced path (future, not
  baseline)," tracked as its own follow-up spec once eval data shows aggregation questions
  are a real failure mode. This spec stores the normalized rows; nothing reads them yet
  beyond what citation/display might need.
- **Not** vision captioning — that's the sibling spec `050-vision-captioning`.
- **Not** any change to `packages/retrieval/filters.py::build_workspace_filter` or the
  isolation model itself — this phase extends what workspace-scoped data exists and ensures
  it's RLS-protected like its siblings, it doesn't change how isolation works.
- **Not** DuckDB or any new query-engine dependency — the doc mentions DuckDB over stored CSV
  as one option for the normalized representation; this spec defaults to Postgres (already
  present, already has the RLS pattern to reuse) unless `plan.md` finds a concrete reason
  Postgres can't do the job.
- **Not** a production data migration or backfill for tables ingested before this phase — new
  Postgres tables are net-new (no existing rows to migrate); documents re-ingested after this
  ships get the new treatment, matching this project's established norm.
- **Not** re-chunking or re-summarizing already-`ready` documents automatically.

## User-facing behavior

No UI yet; observable behavior is at the API-consumer level.

- Uploading a document with tables produces table chunk(s) whose search-relevant text is a
  natural-language summary of the table's contents, not a markdown dump.
- A large table (above whatever size threshold `plan.md` sets) is split into multiple chunks
  by row-group instead of becoming one oversized chunk; each chunk still shows the header
  row, so a chunk found by search is self-describing rather than a headerless fragment.
- Searching for a concept the table's summary describes (e.g. "SLA credit percentages")
  matches even if the exact words don't appear verbatim in the table cells.
- The raw table content (for exact-value display/citation, once a generation phase exists)
  and its column schema are durably stored, not just implicitly present in the embedded
  summary text.
- A caller with `viewer`+ access to a workspace can see table chunks for documents in that
  workspace exactly as with any other content type; a caller without workspace access still
  cannot, for the normalized table rows exactly as for every other workspace-scoped table.

## Acceptance criteria

- [ ] Raw table content (`raw_table`/`csv`) is durably persisted (object storage and/or
      Postgres — `plan.md` decides) rather than only existing in a worker-local debug file.
- [ ] Every newly-ingested table's Qdrant point(s) have their embedded (`text` payload)
      content sourced from an LLM-generated summary, not raw markdown.
- [ ] Column headers and inferred types are stored as structured metadata reachable from the
      table's chunk(s).
- [ ] A new Postgres table stores normalized rows keyed by `(document_id, table_index,
      row_index, column_name)`, added via a migration, with workspace-scoped Row-Level
      Security proven the same way `tests/integration/test_rls.py` proves it for existing
      tables (a cross-workspace read via this table returns zero rows).
- [ ] A table whose row count exceeds the configured threshold produces multiple Qdrant
      chunks (one per row-group), each carrying the repeated header row in its embedded text.
- [ ] A table at or below the threshold still produces exactly one chunk (no regression for
      the common case).
- [ ] `uv run pytest tests/unit` passes with no live services.
- [ ] `uv run pytest tests/integration` passes against the real stack, including ingesting a
      fixture with both a small and a large table and confirming the chunking/summary/schema
      behavior above.
- [ ] `030`'s and `040`'s existing acceptance criteria still hold.
- [ ] `05-multimodal-strategy.md` §2 is updated to mark the baseline table-intelligence
      improvement as implemented.

## Constraints

- Python 3.12, `uv`-managed, `DocumentPortalException`-style error wrapping.
- The new Postgres table(s) must be added via an Alembic migration and must not weaken the
  RLS posture `030` established — this is treated as the same category of change as `030`'s
  migration `0002`, warranting the same scrutiny (per this project's CLAUDE.md: "Auth/
  tenancy/retrieval-filter changes always get a `plan.md`, even when they look small").
- Must not regress any `020`/`030`/`040` acceptance criteria — the full existing integration
  suite must still pass.
- LLM-generated table summaries use the same provider already configured for embeddings/
  vision (OpenAI) unless a concrete reason emerges to use something else.
- Local dev/test must stay runnable the way `040` verified it.

## Open questions

1. **Raw content storage location.** Object storage (mirroring how PDFs/images already work,
   `packages/storage/keys.py`) vs. inline Postgres JSONB vs. both. → `plan.md`.
2. **Row-group chunk size threshold.** By row count, character count, or both? →`plan.md`.
3. **Column type inference approach.** Regex/heuristic-based (cheap, no LLM call) vs.
   LLM-assisted (more accurate for ambiguous columns, adds cost) — leaning heuristic first,
   given this phase already adds one LLM call per table for the summary; a second LLM call
   for schema inference may be unnecessary cost. → `plan.md`.
4. **Table summary prompt wording**, mirroring `050`'s equivalent open question. → `plan.md`.
5. **New table naming/shape** for the normalized rows (`table_cells`, per the architecture
   doc's suggested name) and whether `raw_table`/`csv`/schema metadata live on that same
   table or a separate `table_versions`-style table alongside it (mirroring
   `document_versions`). → `plan.md`.
