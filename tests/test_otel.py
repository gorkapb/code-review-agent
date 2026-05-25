from datetime import datetime

from opentelemetry.trace import format_trace_id

from src.observability.otel import start_span
from src.observability.telemetry_context import build_telemetry_context


def test_enqueue_span_injects_trace_context():
    telemetry_context = build_telemetry_context(
        job_id="job-123",
        queued_at=datetime.fromisoformat("2026-05-24T12:34:56+00:00"),
        request_id="req-123",
    )

    with start_span(
        "enqueue-pr-review",
        pr_url="https://github.com/acme/widget/pull/42",
        telemetry_context=telemetry_context,
        inject_context=True,
    ) as span:
        span_context = span.get_span_context()

    assert telemetry_context["traceparent"].startswith("00-")
    assert format_trace_id(span_context.trace_id) in telemetry_context["traceparent"]


def test_worker_span_continues_enqueue_trace():
    telemetry_context = build_telemetry_context(
        job_id="job-123",
        queued_at=datetime.fromisoformat("2026-05-24T12:34:56+00:00"),
        request_id="req-123",
    )
    with start_span(
        "enqueue-pr-review",
        pr_url="https://github.com/acme/widget/pull/42",
        telemetry_context=telemetry_context,
        inject_context=True,
    ) as enqueue_span:
        enqueue_context = enqueue_span.get_span_context()

    with start_span(
        "analyze-pr-task",
        pr_url="https://github.com/acme/widget/pull/42",
        telemetry_context=telemetry_context,
        continue_from_context=True,
    ) as span:
        worker_context = span.get_span_context()

    assert worker_context.trace_id == enqueue_context.trace_id
