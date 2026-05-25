from datetime import datetime

from opentelemetry.trace import format_trace_id

import src.observability.otel.metrics as otel_metrics_module
from src.config import settings
from src.observability.otel import start_enqueue_span, start_worker_span
from src.observability.otel.setup import (
    _otlp_headers,
    _otlp_metrics_endpoint,
    _otlp_traces_endpoint,
)
from src.observability.telemetry_context import build_telemetry_context


def test_enqueue_span_injects_trace_context():
    telemetry_context = build_telemetry_context(
        job_id="job-123",
        queued_at=datetime.fromisoformat("2026-05-24T12:34:56+00:00"),
        request_id="req-123",
    )

    with start_enqueue_span(
        pr_url="https://github.com/acme/widget/pull/42",
        telemetry_context=telemetry_context,
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
    with start_enqueue_span(
        pr_url="https://github.com/acme/widget/pull/42",
        telemetry_context=telemetry_context,
    ) as enqueue_span:
        enqueue_context = enqueue_span.get_span_context()

    with start_worker_span(
        pr_url="https://github.com/acme/widget/pull/42",
        telemetry_context=telemetry_context,
    ) as span:
        worker_context = span.get_span_context()

    assert worker_context.trace_id == enqueue_context.trace_id


def test_otlp_traces_endpoint_prefers_specific_endpoint(monkeypatch):
    monkeypatch.setattr(
        settings,
        "otel_exporter_otlp_traces_endpoint",
        "http://collector:4318/custom/traces",
    )
    monkeypatch.setattr(settings, "otel_exporter_otlp_endpoint", "http://ignored:4318")

    assert _otlp_traces_endpoint() == "http://collector:4318/custom/traces"


def test_otlp_traces_endpoint_appends_default_trace_path(monkeypatch):
    monkeypatch.setattr(settings, "otel_exporter_otlp_traces_endpoint", "")
    monkeypatch.setattr(
        settings, "otel_exporter_otlp_endpoint", "http://collector:4318"
    )

    assert _otlp_traces_endpoint() == "http://collector:4318/v1/traces"


def test_otlp_metrics_endpoint_prefers_specific_endpoint(monkeypatch):
    monkeypatch.setattr(
        settings,
        "otel_exporter_otlp_metrics_endpoint",
        "http://collector:4318/custom/metrics",
    )
    monkeypatch.setattr(settings, "otel_exporter_otlp_endpoint", "http://ignored:4318")

    assert _otlp_metrics_endpoint() == "http://collector:4318/custom/metrics"


def test_otlp_metrics_endpoint_appends_default_metric_path(monkeypatch):
    monkeypatch.setattr(settings, "otel_exporter_otlp_metrics_endpoint", "")
    monkeypatch.setattr(
        settings, "otel_exporter_otlp_endpoint", "http://collector:4318"
    )

    assert _otlp_metrics_endpoint() == "http://collector:4318/v1/metrics"


def test_otlp_metrics_endpoint_normalizes_trace_path_from_generic_endpoint(
    monkeypatch,
):
    monkeypatch.setattr(settings, "otel_exporter_otlp_metrics_endpoint", "")
    monkeypatch.setattr(
        settings,
        "otel_exporter_otlp_endpoint",
        "http://collector:4318/v1/traces",
    )

    assert _otlp_metrics_endpoint() == "http://collector:4318/v1/metrics"


def test_otlp_headers_parse_standard_env_format(monkeypatch):
    monkeypatch.setattr(
        settings,
        "otel_exporter_otlp_headers",
        "x-api-key=secret,tenant=code-review,malformed",
    )

    assert _otlp_headers() == {
        "tenant": "code-review",
        "x-api-key": "secret",
    }


def test_record_queue_latency_uses_histogram_without_high_cardinality(monkeypatch):
    records = []

    class FakeHistogram:
        def record(self, value, *, attributes):
            records.append((value, attributes))

    monkeypatch.setattr(otel_metrics_module, "_queue_latency", lambda: FakeHistogram())

    latency = otel_metrics_module.record_queue_latency(
        "2999-05-24T12:34:56+00:00",
        operation_name="analyze_pr_task",
    )

    assert latency == 0
    assert records == [
        (
            0,
            {
                "messaging.system": "arq",
                "messaging.destination.name": "arq:queue",
                "messaging.operation.name": "analyze_pr_task",
                "messaging.operation.type": "process",
            },
        )
    ]
