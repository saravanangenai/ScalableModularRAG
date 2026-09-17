# Spec: Vision Captioning for Images

- **ID:** `050-vision-captioning`
- **Roadmap phase:** [08-roadmap.md](../architecture/08-roadmap.md) Phase 6 — Better
  Multimodal Retrieval (`050-059`), the images half —
  [`05-multimodal-strategy.md`](../architecture/05-multimodal-strategy.md) §1
- **Status:** draft
- **Owner:** Saravanan Shanmugam
- **Date:** 2026-09-15

## Problem statement

`packages/parsing/pdf_parser.py::ComplexPDFParser` extracts every embedded image and runs
Tesseract OCR on it (`run_ocr_on_image`); that raw OCR text is the only thing embedded and
searched for `content_type: "image"` chunks (`create_langchain_documents`'s image branch).
OCR only recovers text *rendered inside* an image — a chart, photo, diagram, or logo with
little or no text is nearly unsearchable today, even though the same image is still shown to
the (future) multimodal LLM at answer time. Retrieval, not generation, is the step this
weakens: an image can never be *found* if nothing about what it visually depicts is indexed.

`03-ingestion-workflow.md` already reserves this for Phase 6, explicitly deferred out of
`020-async-ingestion-pipeline`'s scope, and names where it lands: inside the existing
`parsing` job stage, no new stage needed. `040-hybrid-retrieval-reranking` (done) means
whatever text this phase produces for images now benefits from dense+sparse+RRF+rerank
immediately, rather than only dense search as it would have if this had shipped before `040`.

This is also the first multimodal (vision) LLM call anywhere in this codebase — every prior
OpenAI call (`packages/ingestion`, `packages/retrieval`) has been text-only embeddings.

## Goals

- During the `parsing` stage, call a vision-capable LLM once per extracted image with a
  fixed captioning prompt asking for: what the image depicts, any visible text/labels/
  numbers, and its likely purpose in a business/contract/technical document
  (`05-multimodal-strategy.md` §1's exact framing).
- The resulting caption becomes the **primary embedded text** for that image's chunk —
  replacing raw OCR as the dense/sparse embedding source — while the OCR text is **retained
  alongside it** in the payload so an exact string visible in a chart (a number, a label)
  remains findable via the sparse leg even if the caption paraphrases it.
- This is additive to `image_records`' existing shape (`page_number`, `image_index`,
  `image_path`, `image_ext`, `image_ocr_text`) — a new `vision_caption` field, nothing
  removed.
- A captioning failure for one image (LLM error, timeout, content-policy refusal) degrades
  gracefully — that image falls back to OCR-only text, exactly like today's "OCR failure
  degrades gracefully" behavior in `run_ocr_on_image` — it does not fail the whole ingestion
  job, per `03-ingestion-workflow.md` §4's established partial-failure philosophy.
- No new `ingestion_jobs.status` value — captioning is part of the existing `parsing` stage.

## Non-goals

- **Not** the ColPali/late-interaction visual retrieval path
  (`05-multimodal-strategy.md`'s explicit "Advanced path, future, not baseline") — encoding
  pages as patch-embedding grids is a separate, larger follow-up spec once eval data justifies
  it.
- **Not** table intelligence — that is the sibling spec `051-table-intelligence`, split out
  because it's an independently-sized piece of work (its own new Postgres table/migration).
- **Not** any change to `packages/retrieval/filters.py::build_workspace_filter`, RLS, or the
  workspace isolation model — this phase only changes what text gets produced for image
  chunks at ingestion time.
- **Not** exposing captions through any new API surface — they flow through the existing
  `text` Qdrant payload field and existing `POST /workspaces/{workspace_id}/search` response,
  same as any other chunk's text today.
- **Not** a quality benchmark (recall/precision before vs. after captioning) — that's
  `07-evaluation-observability.md` (Phase 7)'s job, per `04-retrieval-design.md` §4's own
  "with vs. without" measurement principle applied to reranking; this phase ships the
  capability, Phase 7 measures it.
- **Not** re-captioning images from documents ingested before this phase — no backfill job;
  new/re-ingested documents get captions going forward, matching this project's established
  "no production data to preserve" norm for schema/pipeline changes (`012`, `030`, `040`).

## User-facing behavior

No UI yet; observable behavior is at the API-consumer level.

- Uploading a document with images produces image chunks whose search-relevant text is a
  vision-generated description of what the image shows, not just whatever text Tesseract
  happened to OCR out of it.
- Searching for a concept an image visually depicts but never states in words (e.g. "the
  system architecture diagram" for a diagram whose only visible text is box labels) now has
  a real chance of matching that image's chunk — today it would only match if the concept's
  exact words happened to appear as OCR'd text.
- Searching for an exact number or label visible in a chart still works — that text is still
  indexed, now alongside the caption rather than instead of it.
- If vision captioning fails for a particular image, ingestion still completes normally; that
  image's chunk is simply OCR-only, same as before this phase existed.

## Acceptance criteria

- [ ] Every newly-ingested image's Qdrant point has its embedded (`text` payload) content
      sourced from the vision caption when captioning succeeds, with OCR text present as a
      separate, always-populated payload field.
- [ ] A captioning failure for one image is logged and that image's chunk falls back to
      OCR-only text; the overall ingestion job still reaches `ready` (not `failed`).
- [ ] An integration test ingests a fixture containing an image with little/no visible text
      (a photo, chart, or diagram) and demonstrates that a semantically-relevant query
      (describing what the image depicts, not quoting visible text) surfaces that image's
      chunk through the hybrid search pipeline — something OCR-only text could not have
      matched.
- [ ] `uv run pytest tests/unit` passes with no live services (the vision LLM call is
      mockable, matching how `packages/retrieval`'s external calls are already tested).
- [ ] `uv run pytest tests/integration` passes against the real stack, including a real
      vision LLM call.
- [ ] `030`'s and `040`'s existing acceptance criteria still hold — workspace isolation and
      hybrid search behavior are unaffected by this change to what text images produce.
- [ ] `05-multimodal-strategy.md` §1 is updated to mark the baseline vision-captioning
      improvement as implemented.

## Constraints

- Python 3.12, `uv`-managed. New code wraps failures as `DocumentPortalException`-style
  exceptions from `packages/exceptions`, matching every other package.
- The vision LLM call must not add a new provider dependency beyond what's already
  configured — OpenAI is already this project's embedding/chat provider
  (`packages/ingestion/config.py`, `packages/retrieval/config.py`); a vision-capable OpenAI
  model is the default assumption unless a concrete reason emerges to use something else.
- Must not regress any `020`/`030`/`040` acceptance criteria — the full existing integration
  suite (35 tests as of `040`) must still pass.
- Local dev/test must stay runnable the way `040` verified it (native Postgres/Keycloak/
  MinIO, Qdrant Cloud, a `--pool=solo` Celery worker on Windows, a real `OPENAI_API_KEY`).
- Captioning is a per-image, per-ingestion cost (API call + latency) — it must not run on
  the query path; it belongs entirely inside the async `parsing` stage, never inside
  `packages/retrieval`.

## Open questions

1. **Exact vision model.** `05-multimodal-strategy.md` names `gpt-4.1-mini` as an example
   ("the same model family already used in `src/generation.py`" — the sibling prototype
   repo, not this one, which has no generation code yet). Confirm the actual current
   OpenAI vision-capable model to target before `plan.md` locks it in, the way `fastembed`'s
   model names were verified against the installed library rather than assumed in `040`.
2. **Caption prompt wording.** The doc gives the three things to ask for (depiction, visible
   text/labels/numbers, likely document purpose) but not exact prompt text. → `plan.md`.
3. **Cost/latency at scale.** One vision LLM call per image adds real ingestion cost/time for
   image-heavy documents (the existing fixture PDF has ~8 image-bearing pages). Is any
   batching, size threshold (e.g. skip captioning trivially small images/icons), or timeout
   tuning needed, or is per-image-per-job acceptable at this project's current scale?
   → `plan.md`.
4. **Degrade-gracefully failure mode granularity.** Should a captioning failure be visible
   anywhere (a warning on the job, a log line) the way OCR failures already produce a
   `[OCR_SKIPPED_OR_FAILED: ...]` marker, or should it be silent (just OCR-only, no marker)?
   → `plan.md`.
