from datetime import datetime

from src.observability import telemetry_context


def test_build_telemetry_context_uses_json_safe_values():
    queued_at = datetime.fromisoformat("2026-05-24T12:34:56+00:00")

    context = telemetry_context.build_telemetry_context(
        job_id="a" * 32,
        queued_at=queued_at,
        request_id="req-123",
        langfuse_trace_id="b" * 32,
    )

    assert context == {
        "job_id": "a" * 32,
        "queued_at": "2026-05-24T12:34:56+00:00",
        "request_id": "req-123",
        "langfuse_trace_id": "b" * 32,
    }


def test_build_telemetry_context_includes_otel_ids_when_available():
    queued_at = datetime.fromisoformat("2026-05-24T12:34:56+00:00")

    context = telemetry_context.build_telemetry_context(
        job_id="job-123",
        queued_at=queued_at,
        request_id="req-123",
        langfuse_trace_id="lf-123",
        otel_trace_id="a" * 32,
        otel_parent_span_id="b" * 16,
    )

    assert context == {
        "job_id": "job-123",
        "queued_at": "2026-05-24T12:34:56+00:00",
        "request_id": "req-123",
        "langfuse_trace_id": "lf-123",
        "otel_trace_id": "a" * 32,
        "otel_parent_span_id": "b" * 16,
    }


def test_new_langfuse_trace_id_derives_trace_id(monkeypatch):
    monkeypatch.setattr(
        telemetry_context,
        "create_trace_id",
        lambda seed: f"trace-for-{seed}",
    )

    assert telemetry_context.new_langfuse_trace_id("job-123") == "trace-for-job-123"
