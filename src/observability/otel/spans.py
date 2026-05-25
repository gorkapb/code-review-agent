from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from opentelemetry.propagate import extract, inject
from opentelemetry.trace import Span, SpanKind, Status, StatusCode

from src.observability.otel.metrics import record_queue_latency
from src.observability.otel.setup import tracer
from src.observability.telemetry_context import TelemetryContext

_ARQ_QUEUE_NAME = "arq:queue"


@contextmanager
def start_enqueue_span(
    *,
    pr_url: str,
    telemetry_context: TelemetryContext,
) -> Iterator[Span]:
    with _start_span(
        "enqueue-pr-review",
        pr_url=pr_url,
        telemetry_context=telemetry_context,
        kind=SpanKind.PRODUCER,
        inject_context=True,
        attributes=_messaging_attributes(
            telemetry_context,
            operation_type="publish",
            operation_name="enqueue_job",
        ),
    ) as span:
        yield span


@contextmanager
def start_worker_span(
    *,
    pr_url: str,
    telemetry_context: TelemetryContext,
) -> Iterator[Span]:
    with _start_span(
        "analyze-pr-task",
        pr_url=pr_url,
        telemetry_context=telemetry_context,
        kind=SpanKind.CONSUMER,
        continue_from_context=True,
        record_queue_latency_metric=True,
        attributes=_messaging_attributes(
            telemetry_context,
            operation_type="process",
            operation_name="analyze_pr_task",
        ),
    ) as span:
        yield span


def record_span_error(
    span: Span,
    error: Exception,
    *,
    code: str | None = None,
) -> None:
    span.record_exception(error)
    span.set_status(Status(StatusCode.ERROR, code or type(error).__name__))
    if code:
        span.set_attribute("code_review.error_code", code)


@contextmanager
def _start_span(
    name: str,
    *,
    pr_url: str,
    telemetry_context: TelemetryContext,
    kind: SpanKind = SpanKind.INTERNAL,
    continue_from_context: bool = False,
    inject_context: bool = False,
    record_queue_latency_metric: bool = False,
    attributes: Mapping[str, Any] | None = None,
) -> Iterator[Span]:
    parent_context = extract(telemetry_context) if continue_from_context else None
    with tracer().start_as_current_span(
        name,
        context=parent_context,
        kind=kind,
    ) as span:
        _set_common_attributes(
            span,
            pr_url=pr_url,
            telemetry_context=telemetry_context,
            record_queue_latency_metric=record_queue_latency_metric,
        )
        if attributes:
            _set_attributes(span, attributes)
        if inject_context:
            inject(telemetry_context)

        try:
            yield span
        except Exception as exc:
            record_span_error(span, exc)
            raise


def _set_common_attributes(
    span: Span,
    *,
    pr_url: str,
    telemetry_context: TelemetryContext,
    record_queue_latency_metric: bool,
) -> None:
    queue_latency_seconds = (
        record_queue_latency(telemetry_context.get("queued_at"))
        if record_queue_latency_metric
        else None
    )
    attributes: dict[str, Any] = {
        "code_review.job_id": telemetry_context.get("job_id"),
        "code_review.pr_url": pr_url,
        "code_review.request_id": telemetry_context.get("request_id"),
        "code_review.queued_at": telemetry_context.get("queued_at"),
    }
    if queue_latency_seconds is not None:
        attributes["code_review.queue.latency_ms"] = round(
            queue_latency_seconds * 1000,
            2,
        )
    _set_attributes(span, attributes)


def _set_attributes(span: Span, attributes: Mapping[str, Any]) -> None:
    span.set_attributes(
        {key: value for key, value in attributes.items() if value is not None}
    )


def _messaging_attributes(
    telemetry_context: TelemetryContext,
    *,
    operation_type: str,
    operation_name: str,
) -> dict[str, Any]:
    return {
        "messaging.system": "arq",
        "messaging.destination.name": _ARQ_QUEUE_NAME,
        "messaging.operation.type": operation_type,
        "messaging.operation.name": operation_name,
        "messaging.message.id": telemetry_context.get("job_id"),
    }
