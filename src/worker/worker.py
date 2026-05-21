import time
from datetime import UTC, datetime

import structlog
from arq.connections import RedisSettings

from src.agent.graph import graph
from src.config import settings
from src.observability.logging import configure_logging
from src.storage.database import AsyncSessionFactory
from src.storage.models import Review, ReviewStatus

logger = structlog.get_logger(__name__)


async def startup(ctx: dict) -> None:
    configure_logging()
    ctx["db_factory"] = AsyncSessionFactory
    logger.info("worker started")


async def analyze_pr_task(ctx: dict, pr_url: str) -> dict:
    job_id: str = ctx["job_id"]
    db_factory = ctx["db_factory"]

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        job_id=job_id, pr_url=pr_url, task="analyze_pr"
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
    start = time.perf_counter()
    final_status = ReviewStatus.complete
    result: dict | None = None
    try:
        result = await graph.ainvoke(
            {"pr_url": pr_url, "diff": "", "observations": [], "metadata": {}}
        )
        logger.info(
            "task completed", duration_ms=round((time.perf_counter() - start) * 1000, 2)
        )
    except Exception:
        final_status = ReviewStatus.failed
        logger.exception(
            "task failed", duration_ms=round((time.perf_counter() - start) * 1000, 2)
        )
        raise
    finally:
        async with db_factory() as session:
            review = await session.get(Review, job_id)
            if review is not None:
                review.status = final_status
                review.result = result
                review.updated_at = datetime.now(UTC)
                await session.commit()
        structlog.contextvars.clear_contextvars()

    return result


class WorkerSettings:
    functions = [analyze_pr_task]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
