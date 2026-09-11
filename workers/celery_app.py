import uuid

from celery import Celery
from langchain_openai import OpenAIEmbeddings
from qdrant_client import QdrantClient

from packages.db.session import get_sync_sessionmaker
from packages.exceptions import IngestionError
from packages.ingestion import Settings as IngestionSettings
from packages.ingestion.pipeline import run_ingestion
from packages.observability import configure_logging, get_logger
from packages.storage.client import StorageClient

configure_logging()
logger = get_logger(__name__)

_settings = IngestionSettings()

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
def run_ingestion_job(self, job_id: str) -> None:
    logger.info(
        "ingestion_job_task_started",
        job_id=job_id,
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

    with session_factory() as session:
        try:
            run_ingestion(
                job_id=uuid.UUID(job_id),
                session=session,
                storage=storage,
                qdrant_client=qdrant_client,
                qdrant_collection=_settings.qdrant_collection_name,
                embeddings=embeddings,
            )
            logger.info("ingestion_job_task_completed", job_id=job_id)
        except IngestionError:
            logger.exception("ingestion_job_task_failed", job_id=job_id)
            raise
