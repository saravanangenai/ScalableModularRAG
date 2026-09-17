import uuid

import prometheus_client
from celery import Celery
from celery.signals import worker_init
from fastembed import SparseTextEmbedding
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from qdrant_client import QdrantClient

from packages.db.session import get_sync_sessionmaker
from packages.exceptions import IngestionError
from packages.ingestion import Settings as IngestionSettings
from packages.ingestion.pipeline import run_ingestion
from packages.observability import configure_logging, configure_sentry, configure_tracing, get_logger
from packages.observability.config import Settings as ObservabilitySettings
from packages.storage.client import StorageClient

configure_logging()
logger = get_logger(__name__)


@worker_init.connect
def _configure_worker_observability(**kwargs) -> None:
    # Deliberately NOT module-level: apps/api/routers/documents.py imports
    # run_ingestion_job from this module to enqueue jobs, so importing this module
    # happens inside the API process too. worker_init only fires when this process is
    # actually running as `celery -A workers.celery_app worker` (fires once regardless
    # of --pool, including --pool=solo) — module-level calls here previously mislabeled
    # the API process's own traces as "mm-rag-worker" (the _configured guard in
    # packages/observability/tracing.py silently no-op'd the API's later, correct
    # configure_tracing("mm-rag-api") call) and made the API process steal port 9100
    # from the real worker.
    configure_tracing("mm-rag-worker")
    observability_settings = ObservabilitySettings()
    configure_sentry(observability_settings.sentry_dsn, observability_settings.environment)
    prometheus_client.start_http_server(9100)
    CeleryInstrumentor().instrument()


_settings = IngestionSettings()
# Built once per worker process, not per task: loading BM25's vocab/IDF stats has a real
# one-time cost that every ingestion job would otherwise repeat.
_sparse_model = SparseTextEmbedding(model_name=_settings.sparse_embedding_model)

app = Celery(
    "mm_rag_ingestion",
    broker=_settings.celery_broker_url,
    backend=_settings.celery_result_backend,
)
app.conf.task_soft_time_limit = 600  # 10 minutes — parsing/OCR-heavy PDFs are the slow path
app.conf.task_time_limit = 660


@app.task(
    bind=True,
    autoretry_for=(IngestionError,),
    retry_backoff=30,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def run_ingestion_job(self, job_id: str, workspace_id: str) -> None:
    logger.info(
        "ingestion_job_task_started",
        job_id=job_id,
        workspace_id=workspace_id,
        attempt=self.request.retries + 1,
    )

    session_factory = get_sync_sessionmaker()
    storage = StorageClient()
    qdrant_client = QdrantClient(
        url=_settings.qdrant_url, api_key=_settings.qdrant_api_key or None
    )
    embeddings = OpenAIEmbeddings(
        model=_settings.openai_embedding_model,
        dimensions=_settings.openai_embedding_dimension,
        api_key=_settings.openai_api_key,
    )
    # Shared by vision captioning (specs/050) and table summarization (specs/051) —
    # lightweight API client, no local model weights to cache, so built per-task like
    # embeddings/qdrant_client above rather than module-scoped like _sparse_model.
    chat_model = ChatOpenAI(
        model=_settings.openai_vision_model, api_key=_settings.openai_api_key
    )

    with session_factory() as session:
        try:
            run_ingestion(
                job_id=uuid.UUID(job_id),
                workspace_id=uuid.UUID(workspace_id),
                session=session,
                storage=storage,
                qdrant_client=qdrant_client,
                qdrant_collection=_settings.qdrant_collection_name,
                embeddings=embeddings,
                sparse_model=_sparse_model,
                chat_model=chat_model,
                table_chunk_row_threshold=_settings.table_chunk_row_threshold,
                table_chunk_group_size=_settings.table_chunk_group_size,
            )
            logger.info("ingestion_job_task_completed", job_id=job_id)
        except IngestionError:
            logger.exception("ingestion_job_task_failed", job_id=job_id)
            raise
