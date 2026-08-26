import uuid

from celery import Celery
from langchain_openai import OpenAIEmbeddings
from qdrant_client import QdrantClient

from packages.auth.context import set_tenant_scope_sync
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
def run_ingestion_job(self, job_id: str, tenant_id: str) -> None:
    """tenant_id is passed explicitly by the enqueuer (apps/api/routers/documents.py), not
    looked up here — ingestion_jobs is RLS-protected, so a worker-side lookup would be
    blocked by the very policy it's trying to unlock. See
    specs/020-async-ingestion-pipeline/plan.md's "Implementation findings"."""
    logger.info(
        "ingestion_job_task_started",
        job_id=job_id,
        tenant_id=tenant_id,
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
        # local=False: this session is dedicated to one job/tenant for its whole lifetime,
        # and run_ingestion commits multiple times as the job advances through stages — a
        # transaction-local GUC would reset on every one of those commits.
        set_tenant_scope_sync(session, uuid.UUID(tenant_id), local=False)
        try:
            run_ingestion(
                job_id=uuid.UUID(job_id),
                tenant_id=uuid.UUID(tenant_id),
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
