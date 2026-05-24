from collections.abc import Mapping
from datetime import datetime
from typing import Any, NotRequired, TypedDict
from uuid import uuid4

from src.observability.langfuse import create_trace_id


class TelemetryContext(TypedDict):
    job_id: str
    queued_at: str
    request_id: str
    langfuse_trace_id: str | None
    otel_trace_id: NotRequired[str]
    otel_parent_span_id: NotRequired[str]


def new_job_id() -> str:
    return uuid4().hex


def new_langfuse_trace_id(job_id: str) -> str | None:
    return create_trace_id(job_id)


def build_telemetry_context(
    *,
    job_id: str,
    queued_at: datetime,
    request_id: str,
    langfuse_trace_id: str | None,
    otel_trace_id: str | None = None,
    otel_parent_span_id: str | None = None,
) -> TelemetryContext:
    context: TelemetryContext = {
        "job_id": job_id,
        "queued_at": queued_at.isoformat(),
        "request_id": request_id,
        "langfuse_trace_id": langfuse_trace_id,
    }
    if otel_trace_id:
        context["otel_trace_id"] = otel_trace_id
    if otel_parent_span_id:
        context["otel_parent_span_id"] = otel_parent_span_id
    return context


def langfuse_trace_metadata(
    *,
    pr_url: str,
    telemetry_context: Mapping[str, Any] | None,
) -> dict[str, str]:
    metadata: dict[str, str] = {"pr_url": pr_url}
    for key in ("job_id", "request_id", "queued_at", "otel_trace_id", "otel_parent_span_id"):
        value = telemetry_context.get(key) if telemetry_context else None
        if isinstance(value, str) and value:
            metadata[key] = value
    return metadata
