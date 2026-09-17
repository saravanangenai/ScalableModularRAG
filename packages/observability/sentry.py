import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration


def configure_sentry(dsn: str | None, environment: str) -> None:
    """Initializes Sentry error tracking. No-ops when dsn is None, so local dev without a
    configured Sentry project still runs fine — call once at API/worker startup."""
    if dsn is None:
        return

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        integrations=[FastApiIntegration(), CeleryIntegration()],
    )
