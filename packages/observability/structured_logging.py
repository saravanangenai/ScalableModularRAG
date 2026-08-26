import logging

import structlog


def configure_logging(level: int = logging.INFO) -> None:
    """Configures structlog for this process. Call once at worker/API startup.

    Events are logged as snake_case_event_name with keyword fields, per CLAUDE.md — e.g.
    `logger.info("ingestion_job_started", job_id=str(job_id), stage="parsing")`.
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None):
    return structlog.get_logger(name)
