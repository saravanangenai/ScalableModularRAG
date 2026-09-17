# Multimodal Strategy — Images and Tables

- **Status:** approved baseline

> ⚠️ **Vision captioning is implemented** —
> [`specs/050-vision-captioning`](../050-vision-captioning/spec.md). It runs in
> `packages/ingestion/pipeline.py::run_ingestion` (not `packages/parsing`, to keep that
> package's zero-network-dependency, easily-unit-tested nature — a plan-level refinement
> this doc didn't originally specify), using `langchain_openai.ChatOpenAI` with
> `gpt-4.1-mini` (confirmed available, not just assumed, before locking it in).
>
> **Table intelligence is implemented** —
> [`specs/051-table-intelligence`](../051-table-intelligence/spec.md), also in
> `packages/ingestion/pipeline.py::run_ingestion`. The normalized-rows table is named
> `document_tables`/`table_cells` (this doc's §2 used the placeholder name `table_cells`
> alone); column-type inference is a local pandas heuristic, not a second LLM call. Both
> tables are workspace-scoped Row-Level Security-protected using the exact one-hop
> `EXISTS`-join-through-`documents` policy shape `030` established, applied from creation
> (migration `0003`) rather than retrofitted.

## 1. Images

### Current limitation (V1)

`src/parsing.py::extract_text_and_images` extracts every embedded image and runs
`pytesseract` OCR on it (`run_ocr_on_image`); that OCR text is what gets embedded and
searched (`content_type: "image"` documents in `create_langchain_documents`). This means a
chart, photo, diagram, or logo with little or no text is nearly unsearchable — OCR only
recovers text *rendered inside* the image, not what the image visually depicts. The original
image itself is still shown to the multimodal LLM at generation time
(`src/generation.py::_image_to_data_url` + `_build_messages`), but only *after* it's already
been retrieved — and retrieval is the step OCR-dependence weakens.

### Baseline improvement: vision captioning at ingestion time (implemented)

```
Image -> Vision Summary/Caption (multimodal LLM call during ingestion) -> Embedding -> Qdrant
```

During the `parsing` stage of ingestion (see `03-ingestion-workflow.md`), for each extracted
image, `packages/ingestion/pipeline.py::run_ingestion` calls
`packages/ingestion/vision.py::caption_image` (`gpt-4.1-mini` via `langchain_openai.ChatOpenAI`)
with the image and a fixed captioning prompt asking for: what the image depicts, any visible
text/labels/numbers, and its likely purpose in a business/contract/technical document. The
resulting caption is combined with OCR text into one embedded blob (`"VISION CAPTION:
{caption}\n\nOCR TEXT: {ocr_text}"`, mirroring the existing `SELECTABLE TEXT:`/`OCR TEXT:`
combined-text pattern page-level chunks already use) — this becomes the **primary embedded
text** for that chunk, while OCR text stays part of the same blob so an exact string visible
in a chart (a number, a label) remains matchable via the sparse/BM25 leg
(`specs/040-hybrid-retrieval-reranking`). The caption is also stored standalone as a
`vision_caption` Qdrant payload field. A captioning failure (API error, timeout,
content-policy refusal) degrades that one image to OCR-only text, exactly like
`run_ocr_on_image`'s existing failure handling — it never fails the ingestion job.

Verified end to end (`tests/integration/test_vision_captioning.py`): a synthetic fixture page
containing a portrait photo with no OCR-able text gets a real caption
("...no discernible numbers or other text"), and a semantic query describing what the photo
depicts (never quoting any visible text, since there isn't any) correctly surfaces it through
the hybrid search pipeline — something OCR-only retrieval could not have done.

Cost/latency tradeoff: one extra LLM call per image at ingestion time (not per query), which
is why this belongs in the async ingestion pipeline (`03-ingestion-workflow.md`) rather than
on the query path.

### Advanced path (future, not baseline): native visual / multivector retrieval

Late-interaction visual retrieval (ColPali/ColQwen2-style): instead of captioning pages into
text, encode each PDF page as an image directly into a grid of patch embeddings, and encode
the query into token embeddings; score with MaxSim (each query token matches its best patch)
rather than a single dense vector per page. This retrieves on *visual layout* — tables,
charts, and diagrams that a caption would lossily summarize — without depending on any text
extraction step at all. Qdrant supports multivector storage that can host this. This is
tracked as a follow-up spec (`specs/0NN-colpali-visual-retrieval/`) once baseline hybrid
retrieval (`04-retrieval-design.md`) and vision captioning are in production and their
quality gaps are measured (see `07-evaluation-observability.md`) — it's a meaningfully
bigger infra lift (a visual embedding model, larger per-page storage) and should be justified
by eval data showing captioning isn't enough for this document mix, not assumed upfront.

## 2. Tables

### Current limitation (V1)

`src/parsing.py::extract_tables` (pdfplumber) produces a `raw_table` (list of lists), a
pandas-rendered `markdown`, and a `csv` string, but only the **markdown** ends up in the
embedded/searchable document (`create_langchain_documents`'s table branch). Markdown is fine
for a human reading the answer, but weak for retrieval (long tables blow past chunk size and
get truncated by `RecursiveCharacterTextSplitter`... except tables are explicitly *not*
split, per `_split`'s content-type check, so a large table becomes one oversized,
mostly-unsearchable chunk) and unusable for exact factual lookups ("what was the amount in
row 14" is not something a markdown-embedding similarity search reliably answers).

### Baseline improvement: table intelligence, not just markdown (implemented)

For each extracted table, `packages/ingestion/pipeline.py::run_ingestion` stores and indexes
four things (extends `ComplexPDFParser.extract_tables`'s existing `table_records` shape):

1. **Raw table content** — already captured (`raw_table`, `csv`); the CSV is uploaded to
   object storage (`packages/storage/keys.py::table_key`, mirroring `image_key`'s exact
   shape) instead of only existing in the local, debug-only `table_records.json`.
2. **Searchable table summary** — `packages/ingestion/table_intelligence.py::summarize_table`,
   one LLM call (`gpt-4.1-mini`, the same shared client `050`'s vision captioning uses) per
   table. This, not the raw markdown, becomes the primary embedded text — same rationale as
   image captions: better semantic surface for retrieval. A summarization failure degrades
   that table's chunks to header+rows only (no `SUMMARY:` section), never the whole raw
   table — each row-group chunk's own content is already self-sufficient.
3. **Headers/schema information** — `infer_column_types` (pandas heuristics: numeric,
   date, currency-affix detection, string fallback — no second LLM call), stored as
   `document_tables.schema_json`.
4. **Normalized structured representation** — `table_cells`, keyed
   `(document_id, table_id, row_index, column_name)`, RLS-protected identically to every
   other document-derived table (migration `0003`, `030`'s established one-hop-join
   pattern). Nothing queries it yet — the text-to-SQL/text-to-pandas path below remains a
   deferred follow-up, per its own non-goal.

Row-group chunking: a table above `table_chunk_row_threshold` (default 20 rows) splits into
`table_chunk_group_size`-row (default 15) chunks, header implicitly preserved in each group
since every group is still a full DataFrame with the same columns
(`packages/ingestion/table_intelligence.py::chunk_table_by_rows`).

Verified end to end (`tests/integration/test_table_intelligence.py`): a real table's summary,
schema, and normalized cells are all correctly persisted and RLS-protected, and the
resulting chunk is searchable with the summary as its primary content. (None of the fixture
PDF's naturally-occurring tables exceed the row-group threshold — the multi-group chunking
arithmetic itself is exactly verified with a synthetic 32-row table in
`tests/unit/test_ingestion_table_intelligence.py` instead.)

Chunking: tables above a size threshold get split by row-groups (not raw text
`RecursiveCharacterTextSplitter`, which would cut a row in half) with the header row repeated
in every chunk, so no chunk loses column context.

### Advanced path (future, not baseline)

A text-to-SQL/text-to-pandas tool the Generation Service can call when a query is classified
as a structured/aggregation question over a known table (sum/count/filter), using the
normalized `table_cells` representation from item 4 above instead of relying on the LLM to
compute over markdown text in-context. Tracked as a follow-up spec once table intelligence
baseline ships and eval data shows aggregation questions are a real failure mode.

## 3. Related docs

- `03-ingestion-workflow.md` — where captioning/summarization runs in the pipeline
- `04-retrieval-design.md` — how caption/summary text feeds hybrid retrieval
- `07-evaluation-observability.md` — how image/table retrieval quality is measured
  specifically (not just aggregate recall)
