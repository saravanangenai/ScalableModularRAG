# Multimodal Strategy — Images and Tables

- **Status:** approved baseline

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

### Baseline improvement: vision captioning at ingestion time

```
Image -> Vision Summary/Caption (multimodal LLM call during ingestion) -> Embedding -> Qdrant
```

During the `parsing` stage of ingestion (see `03-ingestion-workflow.md`), for each extracted
image, call a multimodal LLM (the same model family already used in
`src/generation.py`, e.g. `gpt-4.1-mini`) with the image and a fixed captioning prompt asking
for: what the image depicts, any visible text/labels/numbers, and its likely purpose in a
business/contract/technical document. The resulting caption becomes the **primary embedded
text** for that chunk (replacing raw OCR as the dense/sparse embedding source), while OCR
text is retained alongside it in the payload for exact-string matches (e.g. someone searching
a specific number visible in a chart). This is additive to `image_records` — same shape,
plus a `vision_caption` field.

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

### Baseline improvement: table intelligence, not just markdown

For each extracted table, store and index four things (extends
`ComplexPDFParser.extract_tables`'s existing `table_records` shape):

1. **Raw table content** — already captured (`raw_table`, `csv`); persisted to object
   storage/Postgres instead of only the local `table_records.json` file.
2. **Searchable table summary** — an LLM-generated natural-language description of what the
   table contains (e.g. "Quarterly incident counts by region, 2023-2024, columns: Region,
   Q1..Q4, Total"). This, not the raw markdown, becomes the primary embedded text — same
   rationale as image captions: better semantic surface for retrieval.
3. **Headers/schema information** — column names and inferred types (string/number/date/
   currency), stored as structured metadata so filters and the generation prompt can cite
   "column X" reliably instead of re-parsing markdown at answer time.
4. **Normalized structured representation** — the cleaned rows loaded into a queryable form
   (a `table_cells` Postgres table, or DuckDB over the stored CSV) keyed by
   `(document_id, table_index, row_index, column_name)`, enabling a future text-to-SQL /
   text-to-pandas answer path for exact factual questions ("what was the total for Q3") that
   pure semantic retrieval structurally cannot answer reliably, since it has to match a
   *number*, not a *meaning*.

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
