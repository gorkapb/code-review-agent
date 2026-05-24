from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from arq.connections import RedisSettings, create_pool
from fastapi import FastAPI

from src.api.middleware import RequestLoggingMiddleware
from src.api.routes import router
from src.config import settings
from src.storage.database import engine
from src.storage.models import Base

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all
        )  # dev convenience; prod uses alembic
    app.state.arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    logger.info("application started")
    yield
    await app.state.arq_pool.aclose()
    await engine.dispose()
    logger.info("application stopped")


def create_app() -> FastAPI:
    app = FastAPI(title="Code Review Agent", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestLoggingMiddleware)
    app.include_router(router)
    return app


app = create_app()
