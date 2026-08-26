import datetime
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

from langchain_core.documents import Document as LCDocument
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import QdrantClient, models
from sqlalchemy.orm import Session

from packages.db.models import Document, DocumentVersion, IngestionJob
from packages.exceptions import IngestionError
from packages.ingestion.qdrant_setup import ensure_collection
from packages.parsing import ComplexPDFParser
from packages.storage.client import StorageClient
from packages.storage.keys import image_key

TEXT_CONTENT_TYPES = {"page_text_plus_ocr"}


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
    tenant_id: uuid.UUID,
    *,
    session: Session,
    storage: StorageClient,
    qdrant_client: QdrantClient,
    qdrant_collection: str,
    embeddings: OpenAIEmbeddings,
    chunk_size: int = 2000,
    chunk_overlap: int = 120,
) -> None:
    """Runs one ingestion job end-to-end: parsing -> chunking -> embedding -> indexing ->
    ready, or failed with failure_stage/failure_reason recorded. `session` must already have
    app.current_tenant_id set (session-scoped, not transaction-scoped — see
    packages.auth.context.set_tenant_scope_sync's docstring for why) by the caller
    (workers/celery_app.py) before this function is called; this function commits multiple
    times as the job advances and never sets the GUC itself.
    """
    job = session.get(IngestionJob, job_id)
    if job is None:
        raise IngestionError(f"ingestion job {job_id} not found (or not visible for this tenant)")

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

            parser = ComplexPDFParser(pdf_path=str(pdf_path), output_dir=tmp_dir)
            parsed = parser.parse(save_output=False)

            if not parsed["documents"]:
                raise IngestionError("parser produced no content — nothing to ingest")

            stage = "chunking"
            job.status = stage
            session.commit()

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

                    point_id = _point_id(
                        document_version.id,
                        content_type,
                        metadata.get("page_number", -1),
                        chunk_index,
                        table_index=metadata.get("table_index", ""),
                        image_index=metadata.get("image_index", ""),
                    )

                    prepared.append(LCDocument(page_content=content, metadata=metadata))
                    point_ids.append(point_id)

            if not prepared:
                raise IngestionError("no non-empty chunks produced — nothing to ingest")

            stage = "embedding"
            job.status = stage
            session.commit()

            vectors = embeddings.embed_documents([doc.page_content for doc in prepared])

            stage = "indexing"
            job.status = stage
            session.commit()

            # Extracted images live on local disk (packages/parsing's output) — upload each
            # to object storage so Qdrant's image_path payload field points at a durable,
            # tenant-scoped key instead of a worker-local temp path.
            uploaded_image_keys: dict[str, str] = {}
            for image_record in parsed["images"]:
                local_path = image_record["image_path"]
                key = image_key(
                    tenant_id,
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
            for lc_doc, vector, point_id in zip(prepared, vectors, point_ids):
                metadata = lc_doc.metadata
                local_image_path = metadata.get("image_path")
                points.append(
                    models.PointStruct(
                        id=point_id,
                        vector=vector,
                        payload={
                            "tenant_id": str(tenant_id),
                            "workspace_id": str(document.workspace_id),
                            "document_id": str(document.id),
                            "document_version_id": str(document_version.id),
                            "is_current_version": True,
                            "content_type": metadata.get("content_type"),
                            "page_number": metadata.get("page_number"),
                            "chunk_index": metadata.get("chunk_index"),
                            "table_index": metadata.get("table_index"),
                            "image_index": metadata.get("image_index"),
                            "image_path": uploaded_image_keys.get(local_image_path),
                            "filename": document.filename,
                            "visibility": "workspace",
                            "created_at": _utcnow().isoformat(),
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

    except Exception as exc:
        session.rollback()
        failed_job = session.get(IngestionJob, job_id)
        failed_job.status = "failed"
        failed_job.failure_stage = stage
        failed_job.failure_reason = str(exc)
        failed_job.retry_count = (failed_job.retry_count or 0) + 1
        failed_job.finished_at = _utcnow()
        session.commit()
        raise IngestionError(f"ingestion job {job_id} failed at stage {stage!r}", exc) from exc
