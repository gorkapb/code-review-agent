from collections.abc import Mapping
from datetime import datetime
from typing import Any, NotRequired, TypedDict


class TelemetryContext(TypedDict):
    job_id: str
    queued_at: str
    request_id: str
    tenant_id: str
    traceparent: NotRequired[str]
    tracestate: NotRequired[str]


def build_telemetry_context(
    *,
    job_id: str,
    queued_at: datetime,
    request_id: str,
    tenant_id: str,
) -> TelemetryContext:
    return {
        "job_id": job_id,
        "queued_at": queued_at.isoformat(),
        "request_id": request_id,
        "tenant_id": tenant_id,
    }


def langfuse_trace_metadata(
    *,
    pr_url: str,
    telemetry_context: Mapping[str, Any] | None,
) -> dict[str, str]:
    metadata: dict[str, str] = {"pr_url": pr_url}
    for key in ("job_id", "request_id", "queued_at", "tenant_id"):
        value = telemetry_context.get(key) if telemetry_context else None
        if isinstance(value, str) and value:
            metadata[key] = value
    return metadata
