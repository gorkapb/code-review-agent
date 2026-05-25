from datetime import UTC, datetime

from opentelemetry.metrics import Counter, Histogram

from src.config import settings
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
_job_duration_histogram: Histogram | None = None
_jobs_started_counter: Counter | None = None
_jobs_completed_counter: Counter | None = None
_jobs_failed_counter: Counter | None = None

_DEFAULT_TASK = "analyze_pr"


def record_queue_latency(
    queued_at: str | None,
    *,
    operation_name: str = "analyze_pr_task",
) -> float | None:
    latency_seconds = queue_latency_seconds(queued_at)
    if latency_seconds is None:
        return None

    if _metrics_enabled():
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


def record_job_started(*, task: str = _DEFAULT_TASK) -> None:
    if not _metrics_enabled():
        return

    _jobs_started().add(1, attributes=_job_attributes(task=task))


def record_job_completed(
    duration_seconds: float,
    *,
    task: str = _DEFAULT_TASK,
) -> None:
    if not _metrics_enabled():
        return

    attributes = _job_attributes(task=task, status="complete")
    _jobs_completed().add(1, attributes=attributes)
    _job_duration().record(duration_seconds, attributes=attributes)


def record_job_failed(
    duration_seconds: float,
    *,
    task: str = _DEFAULT_TASK,
    error_code: str = "unexpected_error",
) -> None:
    if not _metrics_enabled():
        return

    attributes = _job_attributes(
        task=task,
        status="failed",
        error_code=error_code,
    )
    _jobs_failed().add(1, attributes=attributes)
    _job_duration().record(duration_seconds, attributes=attributes)


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


def _job_attributes(
    *,
    task: str,
    status: str | None = None,
    error_code: str | None = None,
) -> dict[str, str]:
    attributes = {"code_review.task": task}
    if status is not None:
        attributes["code_review.status"] = status
    if error_code is not None:
        attributes["code_review.error_code"] = error_code
    return attributes


def _metrics_enabled() -> bool:
    return settings.otel_enabled_effective and settings.otel_metrics_enabled


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


def _job_duration() -> Histogram:
    global _job_duration_histogram

    if _job_duration_histogram is None:
        _job_duration_histogram = meter().create_histogram(
            "code_review.job.duration",
            unit="s",
            description="Duration of a PR review job.",
            explicit_bucket_boundaries_advisory=(
                1,
                2.5,
                5,
                10,
                30,
                60,
                120,
                300,
                600,
                1200,
            ),
        )
    return _job_duration_histogram


def _jobs_started() -> Counter:
    global _jobs_started_counter

    if _jobs_started_counter is None:
        _jobs_started_counter = meter().create_counter(
            "code_review.jobs.started",
            unit="{job}",
            description="Number of PR review jobs started.",
        )
    return _jobs_started_counter


def _jobs_completed() -> Counter:
    global _jobs_completed_counter

    if _jobs_completed_counter is None:
        _jobs_completed_counter = meter().create_counter(
            "code_review.jobs.completed",
            unit="{job}",
            description="Number of PR review jobs completed.",
        )
    return _jobs_completed_counter


def _jobs_failed() -> Counter:
    global _jobs_failed_counter

    if _jobs_failed_counter is None:
        _jobs_failed_counter = meter().create_counter(
            "code_review.jobs.failed",
            unit="{job}",
            description="Number of PR review jobs failed.",
        )
    return _jobs_failed_counter
