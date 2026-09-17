# Tasks: Vision Captioning for Images

- **Plan:** [plan.md](plan.md) (approved 2026-09-15)
- **Status:** done — 90/90 unit tests, 36/36 integration tests (full real stack, real vision
  LLM calls). New live proof this feature matters, not just runs: a synthetic fixture page
  with a text-free portrait photo gets a real, accurate caption, and a semantic query
  describing what it depicts (never quoting any visible text, since there isn't any)
  correctly surfaces it through the hybrid pipeline. `030`/`040`'s authorization suite
  re-ran unmodified and stayed green throughout.

Work top to bottom. Each group should leave the system in a runnable state. Check items off
with `- [x]` as completed; do not delete or renumber finished items.

## Group 1 — Config + `caption_image` (isolated, unit-testable)

- [x] Add `openai_vision_model: str = "gpt-4.1-mini"` to
      `packages/ingestion/config.py::Settings`. — files: `packages/ingestion/config.py`,
      `tests/unit/test_ingestion_config.py` — verify: 2 passed.
- [x] Add `packages/ingestion/vision.py::caption_image(chat_model: ChatOpenAI, image_path:
      str) -> str | None` — reads the image file, base64-encodes it, sends a multimodal
      `HumanMessage` asking for depiction, visible text/labels/numbers, and likely document
      purpose; returns the response text, or `None` (logged, not raised) on any failure
      (missing file, LLM error, or a blank response). — files: `packages/ingestion/vision.py`
      (new), `tests/unit/test_ingestion_vision.py` (new) — verify: 4 passed — message shape
      sent, LLM-failure fallback, missing-file fallback, blank-response fallback.

## Group 2 — Wire into the ingestion pipeline

- [x] In `packages/ingestion/pipeline.py::run_ingestion`, add a `chat_model: ChatOpenAI`
      parameter. After `parser.parse()`, before chunking (still the `parsing` stage), loop
      over the image-content-type documents in `parsed["documents"]`; call `caption_image`
      for each; on success, rewrite `page_content` to
      `"IMAGE FOUND ON PAGE {page}\nIMAGE INDEX: {index}\n\nVISION CAPTION:\n{caption}\n\n
      OCR TEXT:\n{ocr_text}"` (OCR text looked up from `parsed["images"]` by
      `(page_number, image_index)`, since it isn't otherwise separately available once
      `create_langchain_documents` has already combined it into `page_content`); on failure
      (`None`), leave today's OCR-only text unchanged. `metadata["vision_caption"]` is set to
      the caption or `None` either way. — files: `packages/ingestion/pipeline.py` — verify:
      `uv run pytest tests/unit` — no regressions (this function still has no dedicated unit
      test, per `040`'s established real-dependencies-over-mocks convention for
      `run_ingestion` specifically — verified live in Group 3 instead).
- [x] Add `"vision_caption": metadata.get("vision_caption")` to the Qdrant point payload
      dict for image-content-type points. — files: `packages/ingestion/pipeline.py` —
      verify: covered by the live point-inspection check in Group 3.
- [x] In `workers/celery_app.py`, construct `ChatOpenAI(model=_settings.openai_vision_model,
      api_key=_settings.openai_api_key)` **per task invocation**, alongside the existing
      `embeddings`/`qdrant_client` construction — not module-scoped like `_sparse_model`,
      since `ChatOpenAI` has no local model weights to cache (deviation from `plan.md`'s
      "once at module scope" wording, corrected there too — the substance, one shared
      client for both captioning and future table summarization, is unchanged). — files:
      `workers/celery_app.py` — verify: `uv run python -c "import workers.celery_app"`
      imports clean.

## Group 3 — Live verification, docs, regression

- [x] Restart the Celery worker (it doesn't hot-reload) and re-run
      `tests/integration/test_upload_and_ingest.py` to confirm ingestion still completes
      end-to-end with the new captioning step in the parsing stage. — files: none — verify:
      1 passed; live point inspection confirmed real, high-quality `vision_caption` values
      matching what each image actually shows (a pricing table, a contract intake form, a
      flowchart) once filtered to the newly-created points — an earlier check against stale
      points from prior `030`/`040` test runs (same collection, different
      `document_version_id`s, never cleared) briefly looked like a failure before that was
      understood.
- [x] Add an integration test: ingest `tests/fixtures/sample.pdf` (page 24, "Appendix I:
      Profile Image for Multimodal Parsing" — a portrait photo confirmed via live caption to
      have "no discernible numbers or other text"), search for a concept it depicts but
      never states in words ("a professional headshot photo... for a team page or LinkedIn
      profile"), confirm that image's chunk surfaces. — files:
      `tests/integration/test_vision_captioning.py` (new) — verify: 1 passed against the
      real stack.
- [x] Re-run `tests/integration/test_search_rbac.py` unmodified — the authorization
      regression gate. — files: none — verify: 5 passed.
- [x] Update `05-multimodal-strategy.md` §1 (marked implemented, notes `gpt-4.1-mini` /
      `packages/ingestion/pipeline.py` as the actual home, the combined-text format, and the
      live verification result) and `03-ingestion-workflow.md` §3 (removed the "not part of
      this stage yet" note). — files:
      `specs/architecture/05-multimodal-strategy.md`,
      `specs/architecture/03-ingestion-workflow.md`.
- [x] Full regression: `uv run pytest tests/unit` and `uv run pytest tests/integration` both
      green. — verify: 90 passed (unit), 36 passed (integration, one combined run of the
      whole `tests/integration` directory).
- [x] `specs/README.md` gains a `050` row; status set to `done`.

## Verification (end of increment)

- [x] All `spec.md` acceptance criteria satisfied.
- [x] `uv run pytest tests/unit` passes with no live services — 90 passed.
- [x] `uv run pytest tests/integration` passes against the full real stack — 36 passed.
- [x] `05-multimodal-strategy.md`, `03-ingestion-workflow.md` updated per `plan.md`'s
      Architecture doc deltas.
- [x] `specs/README.md` gains a `050` row; status set to `done`.
