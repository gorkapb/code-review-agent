from datetime import datetime

from src.observability import telemetry_context


def test_build_telemetry_context_uses_json_safe_values():
    queued_at = datetime.fromisoformat("2026-05-24T12:34:56+00:00")

    context = telemetry_context.build_telemetry_context(
        job_id="a" * 32,
        queued_at=queued_at,
        request_id="req-123",
        tenant_id="tenant-1",
    )

    assert context == {
        "job_id": "a" * 32,
        "queued_at": "2026-05-24T12:34:56+00:00",
        "request_id": "req-123",
        "tenant_id": "tenant-1",
    }
