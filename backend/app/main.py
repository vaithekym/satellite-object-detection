import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import async_sessionmaker

from app import health
from app.api import images, jobs, stats
from app.config import Settings, get_settings
from app.db import create_engine
from app.storage import create_s3_client
from app.worker.celery_app import create_celery


def create_app(settings: Settings | None = None) -> FastAPI:
    """App factory. Run with: uvicorn --factory app.main:create_app"""
    settings = settings or get_settings()
    logging.basicConfig(level=logging.INFO)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        app.state.engine = engine
        app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
        app.state.s3 = create_s3_client(settings)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="Satellite Object Detection API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.celery = create_celery(settings)  # producer only; workers run separately
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )
    app.include_router(health.router)
    app.include_router(images.router)
    app.include_router(jobs.analysis_router)
    app.include_router(jobs.jobs_router)
    app.include_router(stats.router)
    return app
