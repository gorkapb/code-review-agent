import os

from arq.connections import RedisSettings


async def analyze_pr_task(ctx: dict, pr_url: str) -> dict:
    return {"pr_url": pr_url, "status": "received"}


class WorkerSettings:
    functions = [analyze_pr_task]
    redis_settings = RedisSettings.from_dsn(
        os.getenv("REDIS_URL", "redis://localhost:6379")
    )
