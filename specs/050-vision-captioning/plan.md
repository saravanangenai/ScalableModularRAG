# Plan: Vision Captioning for Images

- **Spec:** [spec.md](spec.md) (approved 2026-09-15)
- **Status:** draft

## Summary

Add one vision LLM call per extracted image inside `packages/ingestion/pipeline.py::run_ingestion`
(not `packages/parsing`, to keep that package's current zero-network-dependency, easily
unit-tested nature intact), using `langchain_openai.ChatOpenAI` — already an installed
dependency, no new package needed — with `gpt-4.1-mini` (confirmed available on this
account's OpenAI key, matching the architecture doc's suggestion exactly). The resulting
caption is combined with OCR text into one embedded blob, mirroring the exact
`SELECTABLE TEXT: ... / OCR TEXT: ...` pattern already used for page-level text — no new
concept, just the image branch adopting the pattern the page branch already has. Captioning
failures degrade to OCR-only, matching `run_ocr_on_image`'s existing philosophy.

## Architecture doc deltas

| Doc | Change |
|---|---|
| `05-multimodal-strategy.md` | §1: mark baseline vision captioning as implemented; note the concrete model (`gpt-4.1-mini` via `langchain_openai.ChatOpenAI`) and that captioning runs in `packages/ingestion/pipeline.py`, not `packages/parsing` (a refinement — the doc doesn't specify which package, this plan pins it down). |
| `03-ingestion-workflow.md` | §3 (`parsing` stage description): remove the "Vision captioning ... is not part of this stage yet" note now that it is. |

## Component/module ownership

- **`packages/ingestion/config.py`** — add `openai_vision_model: str = "gpt-4.1-mini"`.
  Ingestion-only (unlike `openai_embedding_model`/`sparse_embedding_model`, there's no
  retrieval-side counterpart that needs to match — captioning only ever happens at ingest
  time, never on the query path).
- **`packages/ingestion/vision.py`** (new) — `caption_image(vision_model: ChatOpenAI,
  image_path: str) -> str | None`: reads the image file, base64-encodes it, sends the
  three-part prompt (depiction / visible text-labels-numbers / likely document purpose) as
  a multimodal `HumanMessage` (confirmed working: `content=[{"type": "text", ...},
  {"type": "image_url", "image_url": {"url": f"data:image/{ext};base64,{b64}"}}]`), returns
  the caption text. Returns `None` (not raises) on any failure — logged via
  `packages/observability`, matching `run_ocr_on_image`'s "never fail the whole parse over
  one bad image" contract, just returning `None` instead of an inline marker string (see
  Open Question 4's resolution below). Isolating this in its own module gives it an
  independent, easily-mocked unit-test seam (`vision_model.invoke` mocked, no real image
  file needed) rather than inlining it into `run_ingestion`.
- **`packages/ingestion/pipeline.py::run_ingestion`** — gains a `vision_model: ChatOpenAI`
  parameter. After `parser.parse()` returns `parsed["documents"]`, before chunking, a new
  pass over the image-content-type documents calls `caption_image` for each (keyed by the
  same `image_path` metadata already present) and rewrites that document's `page_content`
  to `f"IMAGE FOUND ON PAGE {page}\nIMAGE INDEX: {index}\n\nVISION CAPTION:\n{caption}\n\nOCR
  TEXT:\n{ocr_text}"` when captioning succeeds, leaving today's OCR-only text unchanged when
  it doesn't. `metadata["vision_caption"]` is set to the caption (or `None`) either way, so
  it reaches the Qdrant payload independent of what ended up in the embedded text.
- **`workers/celery_app.py`** — constructs `ChatOpenAI(model=_settings.openai_vision_model,
  api_key=_settings.openai_api_key)` per task invocation, alongside the existing
  `embeddings`/`qdrant_client` construction — not module-scoped like `_sparse_model`, since
  `ChatOpenAI` is a lightweight API client wrapper with no local model weights to cache
  (unlike BM25's vocab/IDF stats, which are the actual cost `_sparse_model`'s module-scope
  caching avoids repeating). Passed into `run_ingestion` as `chat_model`.
- **Qdrant payload** (`packages/ingestion/pipeline.py`'s point-building loop) — image points
  gain a `"vision_caption": str | None` field, additive to the existing payload shape.

## Data model changes

- **Qdrant payload**: new `vision_caption` field on image-content-type points. No new
  payload index needed (not a filter field). No collection recreation needed (payload
  schema changes don't require it, unlike `040`'s vector schema change).
- **No Postgres changes.**
- **No new dependency** — `langchain-openai` is already in `pyproject.toml`
  (`langchain-openai>=0.2`); `ChatOpenAI` is a different class from the same package
  `OpenAIEmbeddings` already comes from.

## API contract

No changes. `POST /workspaces/{workspace_id}/search` and its request/response shapes are
untouched — this phase only changes what text gets produced and embedded for image chunks
at ingestion time, and adds one payload field the response schema doesn't currently surface
(consistent with `text` already not being the only payload field left out of
`SearchResultOut` — no change needed there for this phase either, unless `plan.md` wants to
expose `vision_caption` in the API response; deferred, since nothing consumes it yet and
`text` already contains the caption).

## Retrieval / ingestion impact

- **Ingestion**: one additional LLM call per image, real network latency (typically 1-3s per
  call for a small/medium image against `gpt-4.1-mini`), run sequentially per image within
  the existing `parsing` stage — no new job stage, no change to the status state machine.
  For an image-heavy document (the fixture PDF has ~8 image-bearing pages), this adds
  meaningfully to total ingestion time but ingestion is already async and already tolerates
  multi-minute real-world runs on this dev box (documented Windows AV-scan stall in `020`/
  `030`'s test notes) — not a blocker.
- **Retrieval**: none. Captioning never runs on the query path; `packages/retrieval` is
  untouched by this spec.
- Expected quality effect: images become findable by what they depict, not just OCR'd text —
  not measured quantitatively here (Phase 7's job, per spec's own non-goal).

## Security / tenancy impact

None. This spec does not touch `packages/retrieval/filters.py::build_workspace_filter`, RLS,
or any auth/RBAC code path — it only changes what text and payload fields get produced for
image chunks during the existing, already-workspace-scoped ingestion flow. The existing
`030`/`040` authorization test suites are the regression gate (unmodified pass required).

## Rollout

Big-bang, no flag:
- Purely additive: new payload field, new embedded-text shape for images only. Existing
  page/table chunks are untouched.
- No schema migration, so no recreate/downtime concern (unlike `040`'s Qdrant vector schema
  change).
- Revert path: drop the `caption_image` call and payload field addition, image chunks
  revert to OCR-only exactly as before this spec — a single, localized code change to
  revert, no data cleanup required (extra payload field on existing points is harmless if
  ignored).
- Cost control: no rate limiting or batching is built in this phase (Open Question 3
  resolved below) — acceptable at this project's current scale; revisit if a real corpus
  makes per-image-per-job cost/latency a problem.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Vision LLM call fails or times out for a given image | Medium — external API, network-dependent | Low — degrades to OCR-only for that image, doesn't fail the job | `caption_image` catches all exceptions and returns `None`; `run_ingestion` falls back to today's OCR-only `page_content` exactly |
| Ingestion latency grows meaningfully for image-heavy documents | Medium at scale, low at current (assignment) corpus size | Low — ingestion is already async and already tolerates multi-minute runs | Accepted per spec's own constraint ("must not run on the query path" — satisfied); no batching/parallelization built now, revisit if real usage shows it matters |
| Vision LLM content-policy refusal for certain images (e.g. faces, sensitive content) | Low | Low — same as any other failure mode, degrades to OCR-only | Covered by the same catch-all in `caption_image` |
| `gpt-4.1-mini` gets deprecated/renamed upstream | Low | Medium if it happens — ingestion would start failing captioning for every image | Model name is a single config value (`openai_vision_model`), not hardcoded inline — a one-line config change recovers |

## Alternatives considered

- **Running captioning inside `packages/parsing::ComplexPDFParser`** (literally adding
  `vision_caption` to `image_records`, as the spec's Goals section's wording might suggest)
  — rejected: `packages/parsing` currently has zero network/API dependencies and its unit
  tests run with no live services and no mocking
  (`tests/unit/test_parsing_pdf_parser.py`); pulling an LLM call into that class would force
  every future parsing test to either hit a real API or mock one, for a concern (LLM
  orchestration) that already lives in `packages/ingestion` for embeddings. Keeping
  `packages/parsing` pure and doing captioning in `packages/ingestion/pipeline.py` (which
  already orchestrates the OpenAI embeddings call) is more consistent with the existing
  module boundary, even though it means `vision_caption` ends up in the Qdrant
  payload/LangChain metadata rather than literally on `ComplexPDFParser.image_records`.
- **A separate `captioning` job stage** — rejected: `03-ingestion-workflow.md` already
  reserves this work for inside the existing `parsing` stage; adding a new
  `ingestion_jobs.status` value is a bigger, unnecessary state-machine change for one more
  sub-step within parsing.
- **An inline `[CAPTION_FAILED: ...]` marker string** (mirroring `run_ocr_on_image`'s
  `[OCR_SKIPPED_OR_FAILED: ...]` pattern) instead of silent `None` — considered for Open
  Question 4; decided against embedding a failure marker into searchable text (it would
  itself become spuriously matchable/embedddable noise); a log line is enough visibility for
  now, matching the "silent, OCR-only fallback" option the spec's open question raised.
