from datetime import UTC, datetime

from opentelemetry.metrics import Histogram

from src.observability.otel.setup import meter

_ARQ_QUEUE_NAME = "arq:queue"
_QUEUE_LATENCY_BUCKETS_SECONDS = (
    0.1,
    0.25,
    0.5,
    1,
    2.5,
    5,
    10,
    30,
    60,
    120,
    300,
    600,
)

_queue_latency_histogram: Histogram | None = None


def record_queue_latency(
    queued_at: str | None,
    *,
    operation_name: str = "analyze_pr_task",
) -> float | None:
    latency_seconds = queue_latency_seconds(queued_at)
    if latency_seconds is None:
        return None

    _queue_latency().record(
        latency_seconds,
        attributes={
            "messaging.system": "arq",
            "messaging.destination.name": _ARQ_QUEUE_NAME,
            "messaging.operation.name": operation_name,
            "messaging.operation.type": "process",
        },
    )
    return latency_seconds


def queue_latency_seconds(queued_at: str | None) -> float | None:
    if not queued_at:
        return None

    try:
        queued_datetime = datetime.fromisoformat(queued_at)
    except ValueError:
        return None

    if queued_datetime.tzinfo is None:
        queued_datetime = queued_datetime.replace(tzinfo=UTC)
    return round(
        max((datetime.now(UTC) - queued_datetime.astimezone(UTC)).total_seconds(), 0),
        6,
    )


def _queue_latency() -> Histogram:
    global _queue_latency_histogram

    if _queue_latency_histogram is None:
        _queue_latency_histogram = meter().create_histogram(
            "code_review.queue.latency",
            unit="s",
            description="Time a PR review job spends waiting in the queue.",
            explicit_bucket_boundaries_advisory=_QUEUE_LATENCY_BUCKETS_SECONDS,
        )
    return _queue_latency_histogram
