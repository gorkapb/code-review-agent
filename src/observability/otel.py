from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.propagate import extract, inject
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import (
    ProxyTracerProvider,
    Span,
)

from src.config import settings
from src.observability.telemetry_context import TelemetryContext

_TRACER_NAME = "code-review-agent"


def configure_otel() -> None:
    provider = trace.get_tracer_provider()
    if not isinstance(provider, ProxyTracerProvider):
        return

    trace.set_tracer_provider(
        TracerProvider(
            resource=Resource.create(
                {
                    "service.name": settings.service_name,
                    "service.version": settings.service_version,
                    "deployment.environment": settings.env,
                }
            )
        )
    )


@contextmanager
def start_span(
    name: str,
    *,
    pr_url: str,
    telemetry_context: TelemetryContext,
    continue_from_context: bool = False,
    inject_context: bool = False,
) -> Iterator[Span]:
    parent_context = extract(telemetry_context) if continue_from_context else None
    with _tracer().start_as_current_span(name, context=parent_context) as span:
        _set_common_attributes(span, pr_url=pr_url, telemetry_context=telemetry_context)
        if inject_context:
            inject(telemetry_context)
        yield span


def _tracer() -> trace.Tracer:
    configure_otel()
    return trace.get_tracer(_TRACER_NAME, settings.service_version)


def _set_common_attributes(
    span: Span,
    *,
    pr_url: str,
    telemetry_context: TelemetryContext,
) -> None:
    attributes: dict[str, str] = {
        "code_review.job_id": telemetry_context["job_id"],
        "code_review.pr_url": pr_url,
        "code_review.request_id": telemetry_context["request_id"],
        "code_review.queued_at": telemetry_context["queued_at"],
    }
    span.set_attributes(attributes)
