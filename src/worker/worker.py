import os
from datetime import UTC, datetime

from arq.connections import RedisSettings

from src.storage.database import AsyncSessionFactory
from src.storage.models import Review, ReviewStatus


async def startup(ctx: dict) -> None:
    ctx["db_factory"] = AsyncSessionFactory


async def analyze_pr_task(ctx: dict, pr_url: str) -> dict:
    job_id: str = ctx["job_id"]
    db_factory = ctx["db_factory"]

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

    final_status = ReviewStatus.complete
    result: dict | None = None
    try:
        result = {"pr_url": pr_url, "status": "received"}  # real work goes here
    except Exception:
        final_status = ReviewStatus.failed
        raise
    finally:
        async with db_factory() as session:
            review = await session.get(Review, job_id)
            if review is not None:
                review.status = final_status
                review.result = result
                review.updated_at = datetime.now(UTC)
                await session.commit()

    return result


class WorkerSettings:
    functions = [analyze_pr_task]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(
        os.getenv("REDIS_URL", "redis://localhost:6379")
    )
