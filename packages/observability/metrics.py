from prometheus_client import Counter, Histogram

INGESTION_STAGE_DURATION = Histogram(
    "ingestion_stage_duration_seconds",
    "Duration of each ingestion pipeline stage",
    ["stage"],
)
INGESTION_JOBS_TOTAL = Counter(
    "ingestion_jobs_total",
    "Ingestion jobs reaching a terminal status",
    ["status"],
)
RETRIEVAL_STAGE_DURATION = Histogram(
    "retrieval_stage_duration_seconds",
    "Duration of each retrieval pipeline stage",
    ["stage"],
)
