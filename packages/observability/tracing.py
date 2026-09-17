from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Tracer

from packages.observability.config import Settings

_configured = False


def configure_tracing(service_name: str, settings: Settings | None = None) -> None:
    """Configures a global OTel TracerProvider exporting via OTLP-HTTP. Call once at
    API/worker startup, mirroring structured_logging.py's configure_logging shape.

    Safe to call more than once (e.g. across test reloads) — later calls are no-ops rather
    than raising, since OTel only allows one global TracerProvider per process.
    """
    global _configured
    if _configured:
        return

    settings = settings or Settings()
    resource = Resource.create({SERVICE_NAME: service_name})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=f"{settings.otel_exporter_endpoint}/v1/traces")
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _configured = True


def get_tracer(name: str) -> Tracer:
    return trace.get_tracer(name)
