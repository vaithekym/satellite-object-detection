"""Fixtures for integration tests against a real PostgreSQL/PostGIS test database."""

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from botocore.exceptions import BotoCoreError
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import get_settings
from app.main import create_app
from app.storage import ensure_bucket
from tests.api_helpers import TEST_BUCKET, TEST_QUEUE

BACKEND_DIR = Path(__file__).resolve().parents[1]


def alembic_config(url: str) -> Config:
    config = Config(BACKEND_DIR / "alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture(scope="session")
def test_database_url() -> str:
    try:
        url = get_settings().test_database_url
    except Exception:  # missing .env etc.
        url = None
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    database = make_url(url).database or ""
    if not database.endswith("_test"):
        pytest.fail(f"Refusing to run destructive tests against '{database}' (must end in _test)")
    return url


@pytest.fixture(scope="session")
def migrated_database(test_database_url: str) -> Iterator[str]:
    """Wipe the test database, then migrate to head (also exercises downgrade)."""
    config = alembic_config(test_database_url)
    try:
        command.downgrade(config, "base")
    except (OSError, SQLAlchemyError) as exc:
        if "does not exist" in str(exc) or isinstance(exc, OSError):
            reason = f"test database unavailable ({type(exc).__name__})"
            pytest.skip(f"{reason}; see docs/development.md")
        raise
    command.upgrade(config, "head")
    yield test_database_url


@pytest.fixture
async def db_session(migrated_database: str) -> AsyncIterator[AsyncSession]:
    """Session inside a transaction that is rolled back after each test."""
    engine = create_async_engine(migrated_database)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()
    await engine.dispose()


# App wired to the test database and a dedicated MinIO test bucket (cleaned after each test).
@pytest.fixture
async def app(migrated_database: str) -> AsyncIterator[FastAPI]:
    settings = get_settings().model_copy(
        update={
            "database_url": migrated_database,
            "s3_bucket": TEST_BUCKET,
            "analysis_queue": TEST_QUEUE,
            "max_upload_bytes": 20 * 1024 * 1024,
        }
    )
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        s3 = application.state.s3
        try:
            ensure_bucket(s3, TEST_BUCKET)
        except BotoCoreError:
            pytest.skip("MinIO is not running (make minio)")
        try:
            yield application
        finally:
            engine = create_async_engine(migrated_database)
            async with engine.begin() as conn:
                await conn.execute(text("DELETE FROM images"))
            await engine.dispose()
            listed = s3.list_objects_v2(Bucket=TEST_BUCKET)
            for obj in listed.get("Contents", []):
                s3.delete_object(Bucket=TEST_BUCKET, Key=obj["Key"])


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
