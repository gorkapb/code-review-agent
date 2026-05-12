from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from arq.connections import create_pool
from fastapi import FastAPI

from src.api.routes import router
from src.storage.database import engine
from src.storage.models import Base
from src.worker.worker import WorkerSettings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all
        )  # dev convenience; prod uses alembic
    app.state.arq_pool = await create_pool(WorkerSettings.redis_settings)
    yield
    await app.state.arq_pool.aclose()
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="Code Review Agent", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()
