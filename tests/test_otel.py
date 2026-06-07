from datetime import datetime

from opentelemetry.trace import format_trace_id

import src.observability.otel.metrics as otel_metrics_module
from src.config import settings
from src.observability.logging import _add_otel_trace_context
from src.observability.otel import start_enqueue_span, start_worker_span
from src.observability.otel.setup import (
    _metrics_enabled,
    _otlp_headers,
    _otlp_metrics_endpoint,
    _otlp_traces_endpoint,
    _traces_enabled,
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


def test_log_processor_adds_current_trace_context():
    telemetry_context = build_telemetry_context(
        job_id="job-123",
        queued_at=datetime.fromisoformat("2026-05-24T12:34:56+00:00"),
        request_id="req-123",
    )

    with start_enqueue_span(
        pr_url="https://github.com/acme/widget/pull/42",
        telemetry_context=telemetry_context,
    ) as span:
        event = _add_otel_trace_context(None, "", {})

    span_context = span.get_span_context()
    assert event["trace_id"] == format_trace_id(span_context.trace_id)
    assert event["span_id"]


def test_otel_disabled_gates_traces_and_metrics(monkeypatch):
    monkeypatch.setattr(settings, "otel_enabled", False)

    assert _traces_enabled() is False
    assert _metrics_enabled() is False


def test_otel_enabled_respects_per_signal_flags(monkeypatch):
    monkeypatch.setattr(settings, "otel_enabled", True)
    monkeypatch.setattr(settings, "otel_traces_enabled", True)
    monkeypatch.setattr(settings, "otel_metrics_enabled", False)

    assert _traces_enabled() is True
    assert _metrics_enabled() is False


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


def test_job_lifecycle_metrics_use_low_cardinality_attributes(monkeypatch):
    records = []

    class FakeCounter:
        def __init__(self, name):
            self.name = name

        def add(self, value, *, attributes):
            records.append((self.name, value, attributes))

    class FakeHistogram:
        def record(self, value, *, attributes):
            records.append(("duration", value, attributes))

    monkeypatch.setattr(
        otel_metrics_module, "_jobs_started", lambda: FakeCounter("started")
    )
    monkeypatch.setattr(
        otel_metrics_module, "_jobs_completed", lambda: FakeCounter("completed")
    )
    monkeypatch.setattr(
        otel_metrics_module, "_jobs_failed", lambda: FakeCounter("failed")
    )
    monkeypatch.setattr(otel_metrics_module, "_job_duration", lambda: FakeHistogram())

    otel_metrics_module.record_job_started()
    otel_metrics_module.record_job_completed(1.25)
    otel_metrics_module.record_job_failed(
        2.5,
        error_code="missing_anthropic_api_key",
    )

    assert records == [
        ("started", 1, {"code_review.task": "analyze_pr"}),
        (
            "completed",
            1,
            {"code_review.task": "analyze_pr", "code_review.status": "complete"},
        ),
        (
            "duration",
            1.25,
            {"code_review.task": "analyze_pr", "code_review.status": "complete"},
        ),
        (
            "failed",
            1,
            {
                "code_review.task": "analyze_pr",
                "code_review.status": "failed",
                "code_review.error_code": "missing_anthropic_api_key",
            },
        ),
        (
            "duration",
            2.5,
            {
                "code_review.task": "analyze_pr",
                "code_review.status": "failed",
                "code_review.error_code": "missing_anthropic_api_key",
            },
        ),
    ]
