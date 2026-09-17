from opentelemetry.trace import Tracer

from packages.observability.config import Settings
from packages.observability.tracing import configure_tracing, get_tracer


def test_configure_tracing_is_idempotent():
    settings = Settings(_env_file=None)

    configure_tracing("test-service", settings)
    configure_tracing("test-service", settings)  # must not raise


def test_get_tracer_returns_a_real_tracer():
    settings = Settings(_env_file=None)
    configure_tracing("test-service", settings)

    tracer = get_tracer(__name__)

    assert isinstance(tracer, Tracer)
