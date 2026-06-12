from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import uuid4

import structlog
from arq.connections import ArqRedis
from arq.jobs import Job, JobStatus
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.security import CurrentTenant
from src.observability.otel import start_enqueue_span
from src.observability.telemetry_context import (
    build_telemetry_context,
)
from src.storage.database import get_db
from src.storage.models import Review, ReviewStatus

router = APIRouter(prefix="/reviews", tags=["reviews"])

logger = structlog.get_logger(__name__)


class ReviewRequest(BaseModel):
    pr_url: str


class ReviewResponse(BaseModel):
    job_id: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    result: dict[str, Any] | None = None


def _get_arq_pool(request: Request) -> ArqRedis:
    return request.app.state.arq_pool


ArqPool = Annotated[ArqRedis, Depends(_get_arq_pool)]
DbSession = Annotated[AsyncSession, Depends(get_db)]


def new_job_id() -> str:
    return uuid4().hex


@router.post(
    "",
    response_model=ReviewResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue a PR review",
)
async def enqueue_review(
    body: ReviewRequest,
    request: Request,
    tenant: CurrentTenant,
    pool: ArqPool,
    db: DbSession,
) -> ReviewResponse:
    job_id = new_job_id()
    telemetry_context = build_telemetry_context(
        job_id=job_id,
        queued_at=datetime.now(UTC),
        request_id=request.state.request_id,
        tenant_id=tenant.id,
    )
    now = datetime.now(UTC)
    review = Review(
        id=job_id,
        tenant_id=tenant.id,
        pr_url=body.pr_url,
        status=ReviewStatus.pending,
        created_at=now,
        updated_at=now,
    )
    db.add(review)
    await db.commit()

    try:
        with start_enqueue_span(
            pr_url=body.pr_url,
            telemetry_context=telemetry_context,
        ):
            job = await pool.enqueue_job(
                "analyze_pr_task",
                body.pr_url,
                telemetry_context=telemetry_context,
                _job_id=job_id,
            )
    except Exception:
        await _discard_review(db, review)
        logger.exception("failed to enqueue review job", job_id=job_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not enqueue the review job. Please retry.",
        ) from None

    if job is None:
        await _discard_review(db, review)
        logger.warning("duplicate job rejected", job_id=job_id, pr_url=body.pr_url)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A job for this PR is already queued.",
        )
    return ReviewResponse(job_id=job_id)


async def _discard_review(db: AsyncSession, review: Review) -> None:
    """Remove a review row whose job could not be enqueued, so it never orphans."""
    await db.delete(review)
    await db.commit()


@router.get(
    "/{job_id}",
    response_model=JobStatusResponse,
    summary="Get the status of a review job",
)
async def get_review(
    job_id: str, tenant: CurrentTenant, pool: ArqPool, db: DbSession
) -> JobStatusResponse:
    # Postgres-first: terminal states are permanent (no TTL)
    review: Review | None = await db.get(Review, job_id)
    # Scope to the caller's tenant. Return 404 (not 403) so we never reveal that
    # another tenant's job exists.
    if review is not None and review.tenant_id != tenant.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found.",
        )
    if review is not None and review.status in (
        ReviewStatus.complete,
        ReviewStatus.failed,
    ):
        return JobStatusResponse(
            job_id=job_id, status=review.status.value, result=review.result
        )

    # Fall back to ARQ/Redis for queued/in-progress state
    job = Job(job_id, pool)
    job_status = await job.status()

    if job_status == JobStatus.not_found and review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found.",
        )

    if review is not None:
        return JobStatusResponse(job_id=job_id, status=review.status.value, result=None)

    return JobStatusResponse(job_id=job_id, status=job_status.value, result=None)
