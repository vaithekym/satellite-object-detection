import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from kombu.connection import Connection
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.storage import bucket_exists, create_s3_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])

# A check returns a short success detail, or raises on failure.
Check = Callable[[], Awaitable[str | None]]


class DependencyCheckError(Exception):
    """Failure whose message is safe to return to API clients."""


class CheckStatus(BaseModel):
    ok: bool
    detail: str | None = None


class LivenessResponse(BaseModel):
    status: Literal["alive"]


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, CheckStatus]


async def check_postgres(engine: AsyncEngine) -> str:
    async with engine.connect() as conn:
        version = await conn.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname = 'postgis'")
        )
    if version is None:
        raise DependencyCheckError("PostGIS extension is not installed in the database")
    return f"PostGIS {version}"


def check_rabbitmq(url: str, timeout_seconds: float) -> str:
    with Connection(url, connect_timeout=timeout_seconds) as conn:
        conn.connect()
    return "connected"


def check_object_storage(settings: Settings) -> str:
    client = create_s3_client(settings, timeout_seconds=settings.health_check_timeout_seconds)
    if not bucket_exists(client, settings.s3_bucket):
        raise DependencyCheckError(
            f"Bucket '{settings.s3_bucket}' does not exist (run `make init-storage`)"
        )
    return f"bucket '{settings.s3_bucket}'"


def get_readiness_checks(request: Request) -> dict[str, Check]:
    settings: Settings = request.app.state.settings
    engine: AsyncEngine = request.app.state.engine
    timeout = settings.health_check_timeout_seconds
    return {
        "postgres": lambda: check_postgres(engine),
        "rabbitmq": lambda: asyncio.to_thread(check_rabbitmq, settings.rabbitmq_url, timeout),
        "object_storage": lambda: asyncio.to_thread(check_object_storage, settings),
    }


async def _run_check(name: str, check: Check, timeout_seconds: float) -> CheckStatus:
    try:
        detail = await asyncio.wait_for(check(), timeout=timeout_seconds)
    except DependencyCheckError as exc:
        return CheckStatus(ok=False, detail=str(exc))
    except TimeoutError:
        return CheckStatus(ok=False, detail="timed out")
    except Exception as exc:
        # Log the full error server-side; return only the error type to clients.
        logger.warning("Readiness check %s failed", name, exc_info=True)
        return CheckStatus(ok=False, detail=f"unavailable ({type(exc).__name__})")
    return CheckStatus(ok=True, detail=detail)


@router.get("/live")
async def live() -> LivenessResponse:
    return LivenessResponse(status="alive")


@router.get(
    "/ready",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
async def ready(
    request: Request,
    response: Response,
    checks: Annotated[dict[str, Check], Depends(get_readiness_checks)],
) -> ReadinessResponse:
    timeout: float = request.app.state.settings.health_check_timeout_seconds
    names = list(checks)
    results = await asyncio.gather(*(_run_check(n, checks[n], timeout) for n in names))
    statuses = dict(zip(names, results, strict=True))
    all_ok = all(s.ok for s in results)
    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ready" if all_ok else "not_ready", checks=statuses)
