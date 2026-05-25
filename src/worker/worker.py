import time
from datetime import UTC, datetime
from typing import Any

import structlog
from arq.connections import RedisSettings

from src.agent.graph import graph
from src.agent.services.github_pull_request_diff import PullRequestDiffError
from src.agent.services.pull_request_review import PullRequestReviewError
from src.config import settings
from src.observability.langfuse import (
    create_trace_id,
    flush_langfuse,
    propagate_langfuse_attributes,
    shutdown_langfuse,
    start_langfuse_observation,
)
from src.observability.logging import configure_logging
from src.observability.otel import (
    configure_otel,
    record_job_completed,
    record_job_failed,
    record_job_started,
    record_span_error,
    shutdown_otel,
    start_worker_span,
)
from src.observability.telemetry_context import (
    TelemetryContext,
    langfuse_trace_metadata,
)
from src.storage.database import AsyncSessionFactory, engine
from src.storage.models import Review, ReviewStatus

logger = structlog.get_logger(__name__)


async def startup(ctx: dict) -> None:
    configure_logging()
    configure_otel(sqlalchemy_engine=engine)
    ctx["db_factory"] = AsyncSessionFactory
    logger.info("worker started")


async def shutdown(ctx: dict) -> None:
    shutdown_langfuse()
    shutdown_otel()
    logger.info("worker stopped")


async def analyze_pr_task(
    ctx: dict,
    pr_url: str,
    *,
    telemetry_context: TelemetryContext,
) -> dict:
    job_id: str = ctx["job_id"]
    db_factory = ctx["db_factory"]
    trace_metadata = langfuse_trace_metadata(
        pr_url=pr_url,
        telemetry_context=telemetry_context,
    )

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        job_id=job_id,
        pr_url=pr_url,
        request_id=telemetry_context["request_id"],
        task="analyze_pr",
    )

    async with db_factory() as session:
        review = Review(
            id=job_id,
            pr_url=pr_url,
            status=ReviewStatus.running,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(review)
        await session.commit()

    logger.info("task started")
    record_job_started()
    start = time.perf_counter()
    final_status = ReviewStatus.complete
    result: dict = {}

    try:
        with start_worker_span(
            pr_url=pr_url,
            telemetry_context=telemetry_context,
        ) as span:
            with start_langfuse_observation(
                name="review-pull-request",
                as_type="agent",
                input={"job_id": job_id, "pr_url": pr_url},
                metadata=trace_metadata,
                trace_id=create_trace_id(job_id),
            ) as observation:
                try:
                    with propagate_langfuse_attributes(
                        trace_name="review-pull-request",
                        metadata=trace_metadata,
                        tags=["code-review-agent", "pull-request-review"],
                    ):
                        result = await graph.ainvoke(
                            {
                                "pr_url": pr_url,
                                "diff": "",
                                "findings": [],
                                "metadata": {},
                            }
                        )
                    duration_seconds = time.perf_counter() - start
                    record_job_completed(duration_seconds)
                    duration_ms = round(duration_seconds * 1000, 2)
                    logger.info("task completed", duration_ms=duration_ms)
                except PullRequestDiffError as exc:
                    final_status = ReviewStatus.failed
                    result = _failure_result(pr_url, exc)
                    record_span_error(span, exc, code=exc.code)
                    duration_seconds = time.perf_counter() - start
                    record_job_failed(duration_seconds, error_code=exc.code)
                    duration_ms = round(duration_seconds * 1000, 2)
                    logger.error(
                        "task failed", duration_ms=duration_ms, error_code=exc.code
                    )
                except PullRequestReviewError as exc:
                    final_status = ReviewStatus.failed
                    result = _failure_result(pr_url, exc)
                    record_span_error(span, exc, code=exc.code)
                    duration_seconds = time.perf_counter() - start
                    record_job_failed(duration_seconds, error_code=exc.code)
                    duration_ms = round(duration_seconds * 1000, 2)
                    logger.error(
                        "task failed", duration_ms=duration_ms, error_code=exc.code
                    )
                except Exception as exc:
                    final_status = ReviewStatus.failed
                    result = _failure_result(pr_url, exc)
                    duration_seconds = time.perf_counter() - start
                    record_job_failed(duration_seconds)
                    duration_ms = round(duration_seconds * 1000, 2)
                    logger.exception("task failed", duration_ms=duration_ms)
                    raise
                finally:
                    if observation is not None:
                        observation.update(
                            output=_trace_task_output(final_status, result),
                            level="ERROR"
                            if final_status == ReviewStatus.failed
                            else "DEFAULT",
                        )
    finally:
        async with db_factory() as session:
            review = await session.get(Review, job_id)
            if review is not None:
                review.status = final_status
                review.result = result
                review.updated_at = datetime.now(UTC)
                await session.commit()
        flush_langfuse()
        structlog.contextvars.clear_contextvars()

    return result


def _failure_result(pr_url: str, error: Exception) -> dict[str, Any]:
    if isinstance(error, PullRequestDiffError | PullRequestReviewError):
        error_payload = error.to_dict()
    else:
        error_payload = {
            "type": "review_failed",
            "code": "unexpected_error",
            "message": "Unexpected error while reviewing pull request.",
        }

    return {
        "pr_url": pr_url,
        "diff": "",
        "findings": [],
        "metadata": {},
        "error": error_payload,
    }


def _trace_task_output(status: ReviewStatus, result: dict[str, Any]) -> dict[str, Any]:
    error = result.get("error")
    metadata = result.get("metadata", {})
    findings = result.get("findings", [])
    output: dict[str, Any] = {
        "status": status.value,
        "finding_count": len(findings) if isinstance(findings, list) else None,
        "repository": metadata.get("repository")
        if isinstance(metadata, dict)
        else None,
        "pull_number": metadata.get("pull_number")
        if isinstance(metadata, dict)
        else None,
    }
    if isinstance(error, dict):
        output["error_code"] = error.get("code")
    return output


class WorkerSettings:
    functions = [analyze_pr_task]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
