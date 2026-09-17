import datetime
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
from fastembed import SparseTextEmbedding
from langchain_core.documents import Document as LCDocument
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import QdrantClient, models
from sqlalchemy.orm import Session

from packages.db.models import Document, DocumentTable, DocumentVersion, IngestionJob, TableCell
from packages.db.rls import set_workspace_scope_sync
from packages.exceptions import IngestionError
from packages.ingestion.qdrant_setup import ensure_collection
from packages.ingestion.table_intelligence import (
    chunk_table_by_rows,
    infer_column_types,
    summarize_table,
)
from packages.ingestion.vision import caption_image
from packages.observability import INGESTION_JOBS_TOTAL, INGESTION_STAGE_DURATION, get_tracer
from packages.parsing import ComplexPDFParser
from packages.storage.client import StorageClient
from packages.storage.keys import image_key, table_key

TEXT_CONTENT_TYPES = {"page_text_plus_ocr"}

_tracer = get_tracer(__name__)


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def _split(document: LCDocument, splitter: RecursiveCharacterTextSplitter) -> list[LCDocument]:
    content_type = str(document.metadata.get("content_type", "unknown"))
    if content_type in TEXT_CONTENT_TYPES:
        return splitter.split_documents([document])
    return [document]


def _point_id(
    document_version_id: uuid.UUID,
    content_type: str,
    page_number: object,
    chunk_index: int,
    table_index: object = "",
    image_index: object = "",
) -> str:
    identity = "|".join(
        [
            str(document_version_id),
            str(page_number),
            content_type,
            str(table_index),
            str(image_index),
            str(chunk_index),
        ]
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"mm-rag-point:{identity}"))


def run_ingestion(
    job_id: uuid.UUID,
    *,
    workspace_id: uuid.UUID,
    session: Session,
    storage: StorageClient,
    qdrant_client: QdrantClient,
    qdrant_collection: str,
    embeddings: OpenAIEmbeddings,
    sparse_model: SparseTextEmbedding,
    chat_model: ChatOpenAI,
    chunk_size: int = 2000,
    chunk_overlap: int = 120,
    table_chunk_row_threshold: int = 20,
    table_chunk_group_size: int = 15,
) -> None:
    """Runs one ingestion job end-to-end: parsing -> chunking -> embedding -> indexing ->
    ready, or failed with failure_stage/failure_reason recorded. This function commits
    multiple times as the job advances through stages.

    This runs in the Celery worker, never through apps/api/deps/rbac.py — so it must set
    the workspace RLS scope itself, first thing, using the workspace_id the already-authorized
    enqueuing request (apps/api/routers/documents.py::upload_document) passed through
    workers/celery_app.py. Every table touched below (ingestion_jobs, document_versions,
    documents) is RLS-protected (packages/db/migrations/versions/0002_workspace_rls.py); the
    very first read a few lines down would otherwise return nothing.
    """
    set_workspace_scope_sync(session, workspace_id)

    job = session.get(IngestionJob, job_id)
    if job is None:
        raise IngestionError(f"ingestion job {job_id} not found")

    document_version = session.get(DocumentVersion, job.document_version_id)
    document = session.get(Document, job.document_id)

    stage = "parsing"
    try:
        job.status = stage
        job.started_at = _utcnow()
        session.commit()

        pdf_bytes = storage.download(document_version.object_storage_key)

        with TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "input.pdf"
            pdf_path.write_bytes(pdf_bytes)

            with (
                _tracer.start_as_current_span("ingestion.parsing"),
                INGESTION_STAGE_DURATION.labels(stage="parsing").time(),
            ):
                parser = ComplexPDFParser(pdf_path=str(pdf_path), output_dir=tmp_dir)
                parsed = parser.parse(save_output=False)

                if not parsed["documents"]:
                    raise IngestionError("parser produced no content — nothing to ingest")

                # Vision captioning (specs/050-vision-captioning) — still the "parsing" stage,
                # per specs/architecture/03-ingestion-workflow.md. A captioning failure for one
                # image degrades that image's chunk to OCR-only (caption_image never raises);
                # it never fails the job.
                image_ocr_by_key = {
                    (image["page_number"], image["image_index"]): image["image_ocr_text"]
                    for image in parsed["images"]
                }
                with _tracer.start_as_current_span("ingestion.vision_captioning"):
                    for lc_doc in parsed["documents"]:
                        if lc_doc.metadata.get("content_type") != "image":
                            continue
                        image_path = lc_doc.metadata.get("image_path")
                        caption = caption_image(chat_model, image_path) if image_path else None
                        lc_doc.metadata["vision_caption"] = caption
                        if caption:
                            page_number = lc_doc.metadata.get("page_number")
                            image_index = lc_doc.metadata.get("image_index")
                            ocr_text = image_ocr_by_key.get((page_number, image_index), "")
                            lc_doc.page_content = (
                                f"IMAGE FOUND ON PAGE {page_number}\n"
                                f"IMAGE INDEX: {image_index}\n\n"
                                f"VISION CAPTION:\n{caption}\n\n"
                                f"OCR TEXT:\n{ocr_text}"
                            ).strip()

                # Table intelligence (specs/051-table-intelligence) — still the "parsing"
                # stage. A summarization failure for one table degrades that table's chunks
                # to header+rows only, no SUMMARY section (summarize_table never raises); it
                # never fails the job. Raw table LCDocuments are replaced with
                # one-per-row-group documents; chunking below leaves them alone
                # (content_type "table" is not in TEXT_CONTENT_TYPES, so _split is a no-op
                # on each already-split group).
                non_table_documents = [
                    lc_doc
                    for lc_doc in parsed["documents"]
                    if lc_doc.metadata.get("content_type") != "table"
                ]
                table_documents: list[LCDocument] = []
                new_table_cells: list[TableCell] = []

                with _tracer.start_as_current_span("ingestion.table_summarization"):
                    for table_record in parsed["tables"]:
                        page_number = table_record["page_number"]
                        table_index = table_record["table_index"]
                        raw_table = table_record["raw_table"]

                        try:
                            dataframe = pd.DataFrame(raw_table[1:], columns=raw_table[0])
                        except Exception:
                            dataframe = pd.DataFrame(raw_table)

                        storage_key = table_key(
                            document.workspace_id, document.id, document_version.id, table_index
                        )
                        storage.upload(storage_key, table_record["csv"].encode("utf-8"))

                        schema = infer_column_types(dataframe)
                        summary = summarize_table(chat_model, table_record["markdown"])

                        document_table = DocumentTable(
                            document_id=document.id,
                            document_version_id=document_version.id,
                            table_index=table_index,
                            page_number=page_number,
                            object_storage_key=storage_key,
                            summary=summary,
                            schema_json=schema,
                            row_count=len(dataframe),
                        )
                        session.add(document_table)
                        session.flush()  # TableCell.table_id needs document_table.id

                        for row_index, row in dataframe.reset_index(drop=True).iterrows():
                            for column_name, value in row.items():
                                new_table_cells.append(
                                    TableCell(
                                        table_id=document_table.id,
                                        document_id=document.id,
                                        row_index=row_index,
                                        column_name=str(column_name),
                                        value=None if pd.isna(value) else str(value),
                                    )
                                )

                        row_groups = chunk_table_by_rows(
                            dataframe, table_chunk_row_threshold, table_chunk_group_size
                        )
                        header = ", ".join(str(c) for c in dataframe.columns)
                        for group_index, group_df in enumerate(row_groups, start=1):
                            summary_section = f"SUMMARY:\n{summary}\n\n" if summary else ""
                            table_text = (
                                f"TABLE ON PAGE {page_number}, TABLE {table_index} "
                                f"(part {group_index} of {len(row_groups)}):\n\n"
                                f"{summary_section}"
                                f"HEADER: {header}\n\n"
                                f"ROWS:\n{group_df.to_markdown(index=False)}"
                            ).strip()
                            table_documents.append(
                                LCDocument(
                                    page_content=table_text,
                                    metadata={
                                        "source": str(pdf_path),
                                        "page_number": page_number,
                                        "content_type": "table",
                                        "table_index": table_index,
                                        "table_id": str(document_table.id),
                                        "row_group_index": group_index,
                                        "row_group_count": len(row_groups),
                                    },
                                )
                            )

                if new_table_cells:
                    session.add_all(new_table_cells)
                    session.flush()

                parsed["documents"] = non_table_documents + table_documents

            stage = "chunking"
            job.status = stage
            session.commit()

            with (
                _tracer.start_as_current_span("ingestion.chunking"),
                INGESTION_STAGE_DURATION.labels(stage="chunking").time(),
            ):
                splitter = RecursiveCharacterTextSplitter(
                    chunk_size=chunk_size, chunk_overlap=chunk_overlap, add_start_index=True
                )
                prepared: list[LCDocument] = []
                point_ids: list[str] = []

                for lc_doc in parsed["documents"]:
                    for chunk_index, chunk in enumerate(_split(lc_doc, splitter)):
                        content = chunk.page_content.strip()
                        if not content:
                            continue

                        metadata = dict(chunk.metadata)
                        content_type = str(metadata.get("content_type", "unknown"))
                        metadata["chunk_index"] = chunk_index

                        # A row-group-split table (specs/051-table-intelligence) produces
                        # multiple LCDocuments that each individually pass through _split as
                        # a single-item, un-split list — chunk_index alone would be 0 for
                        # every group, colliding on the same deterministic point_id and
                        # silently overwriting each other on upsert. row_group_index
                        # disambiguates them; it's absent (None) for every
                        # non-table-row-group chunk, so their point_id computation is
                        # unaffected.
                        table_index_for_id = metadata.get("table_index", "")
                        row_group_index = metadata.get("row_group_index")
                        if row_group_index is not None:
                            table_index_for_id = f"{table_index_for_id}-{row_group_index}"

                        point_id = _point_id(
                            document_version.id,
                            content_type,
                            metadata.get("page_number", -1),
                            chunk_index,
                            table_index=table_index_for_id,
                            image_index=metadata.get("image_index", ""),
                        )

                        prepared.append(LCDocument(page_content=content, metadata=metadata))
                        point_ids.append(point_id)

                if not prepared:
                    raise IngestionError("no non-empty chunks produced — nothing to ingest")

            stage = "embedding"
            job.status = stage
            session.commit()

            with (
                _tracer.start_as_current_span("ingestion.embedding"),
                INGESTION_STAGE_DURATION.labels(stage="embedding").time(),
            ):
                vectors = embeddings.embed_documents([doc.page_content for doc in prepared])
                # BM25 (specs/040-hybrid-retrieval-reranking) — a statistical term-frequency
                # method, not a neural forward pass, so this adds negligible time next to the
                # dense embedding call above. .embed() (not .query_embed()) matches how the
                # sparse leg embeds queries at read time (packages/retrieval/sparse.py).
                sparse_vectors = list(
                    sparse_model.embed([doc.page_content for doc in prepared])
                )

            stage = "indexing"
            job.status = stage
            session.commit()

            with (
                _tracer.start_as_current_span("ingestion.indexing"),
                INGESTION_STAGE_DURATION.labels(stage="indexing").time(),
            ):
                # Extracted images live on local disk (packages/parsing's output) — upload
                # each to object storage so Qdrant's image_path payload field points at a
                # durable, workspace-scoped key instead of a worker-local temp path.
                uploaded_image_keys: dict[str, str] = {}
                for image_record in parsed["images"]:
                    local_path = image_record["image_path"]
                    key = image_key(
                        document.workspace_id,
                        document.id,
                        document_version.id,
                        image_record["image_index"],
                    )
                    with open(local_path, "rb") as file:
                        storage.upload(key, file.read())
                    uploaded_image_keys[local_path] = key

                ensure_collection(qdrant_client, qdrant_collection, vector_size=len(vectors[0]))

                points: list[models.PointStruct] = []
                for lc_doc, vector, sparse_vector, point_id in zip(
                    prepared, vectors, sparse_vectors, point_ids
                ):
                    metadata = lc_doc.metadata
                    local_image_path = metadata.get("image_path")
                    points.append(
                        models.PointStruct(
                            id=point_id,
                            # "" addresses the existing unnamed/default dense vector;
                            # "sparse" is the named BM25 vector
                            # (packages/ingestion/qdrant_setup.py) — both live on the same
                            # point, not two separate points.
                            vector={
                                "": vector,
                                "sparse": models.SparseVector(
                                    indices=sparse_vector.indices.tolist(),
                                    values=sparse_vector.values.tolist(),
                                ),
                            },
                            payload={
                                "workspace_id": str(document.workspace_id),
                                "document_id": str(document.id),
                                "document_version_id": str(document_version.id),
                                "is_current_version": True,
                                "content_type": metadata.get("content_type"),
                                "page_number": metadata.get("page_number"),
                                "chunk_index": metadata.get("chunk_index"),
                                "table_index": metadata.get("table_index"),
                                "table_id": metadata.get("table_id"),
                                "row_group_index": metadata.get("row_group_index"),
                                "row_group_count": metadata.get("row_group_count"),
                                "image_index": metadata.get("image_index"),
                                "image_path": uploaded_image_keys.get(local_image_path),
                                "vision_caption": metadata.get("vision_caption"),
                                "filename": document.filename,
                                "visibility": "workspace",
                                "created_at": _utcnow().isoformat(),
                                # The chunk's source text — embedded above, but until
                                # specs/030-workspace-rbac-filtering nothing stored it, so a
                                # search result had a score and metadata but no content to
                                # show.
                                "text": lc_doc.page_content,
                            },
                        )
                    )

                qdrant_client.upsert(collection_name=qdrant_collection, points=points, wait=True)

                previous_version_id = document.current_version_id
                if previous_version_id is not None and previous_version_id != document_version.id:
                    qdrant_client.set_payload(
                        collection_name=qdrant_collection,
                        payload={"is_current_version": False},
                        points=models.Filter(
                            must=[
                                models.FieldCondition(
                                    key="document_version_id",
                                    match=models.MatchValue(value=str(previous_version_id)),
                                )
                            ]
                        ),
                        wait=True,
                    )
                    previous_version = session.get(DocumentVersion, previous_version_id)
                    if previous_version is not None:
                        previous_version.is_current = False
                        previous_version.superseded_at = _utcnow()

                document_version.is_current = True
                document_version.page_count = len(parsed["pages"])
                document.current_version_id = document_version.id
                document.content_hash_current = document_version.content_hash
                document.status = "ready"

                job.status = "ready"
                job.finished_at = _utcnow()
                session.commit()
                INGESTION_JOBS_TOTAL.labels(status="ready").inc()

    except Exception as exc:
        session.rollback()
        failed_job = session.get(IngestionJob, job_id)
        failed_job.status = "failed"
        failed_job.failure_stage = stage
        failed_job.failure_reason = str(exc)
        failed_job.retry_count = (failed_job.retry_count or 0) + 1
        failed_job.finished_at = _utcnow()
        session.commit()
        INGESTION_JOBS_TOTAL.labels(status="failed").inc()
        raise IngestionError(f"ingestion job {job_id} failed at stage {stage!r}", exc) from exc
