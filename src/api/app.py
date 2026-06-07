from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from arq.connections import RedisSettings, create_pool
from fastapi import FastAPI

from src.api.middleware import RequestLoggingMiddleware
from src.api.routes import router
from src.config import settings
from src.observability.otel import (
    configure_otel,
    instrument_fastapi_app,
    shutdown_otel,
)
from src.storage.database import engine

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_otel(sqlalchemy_engine=engine)
    # Schema is owned by Alembic (`alembic upgrade head`), run as the
    # pre-deploy step. The app never creates tables itself.
    app.state.arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    logger.info("application started")
    yield
    await app.state.arq_pool.aclose()
    await engine.dispose()
    shutdown_otel()
    logger.info("application stopped")


def create_app() -> FastAPI:
    app = FastAPI(title="Code Review Agent", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestLoggingMiddleware)
    app.include_router(router)
    instrument_fastapi_app(app)
    return app


app = create_app()
