from packages.observability.metrics import (
    INGESTION_JOBS_TOTAL,
    INGESTION_STAGE_DURATION,
    RETRIEVAL_STAGE_DURATION,
)


def test_ingestion_stage_duration_records_a_timed_observation():
    with INGESTION_STAGE_DURATION.labels(stage="parsing").time():
        pass

    assert INGESTION_STAGE_DURATION.labels(stage="parsing")._sum.get() >= 0


def test_ingestion_jobs_total_counter_increments():
    before = INGESTION_JOBS_TOTAL.labels(status="ready")._value.get()

    INGESTION_JOBS_TOTAL.labels(status="ready").inc()

    assert INGESTION_JOBS_TOTAL.labels(status="ready")._value.get() == before + 1


def test_retrieval_stage_duration_records_a_timed_observation():
    with RETRIEVAL_STAGE_DURATION.labels(stage="dense_search").time():
        pass

    assert RETRIEVAL_STAGE_DURATION.labels(stage="dense_search")._sum.get() >= 0
