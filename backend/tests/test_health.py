import asyncio

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.config import Settings
from app.health import Check, DependencyCheckError, get_readiness_checks
from app.main import create_app


def make_app(checks: dict[str, Check] | None = None, timeout: float = 1.0) -> FastAPI:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://test@localhost/test",
        s3_access_key="test",
        s3_secret_key=SecretStr("test-secret"),
        health_check_timeout_seconds=timeout,
    )
    app = create_app(settings)
    if checks is not None:
        app.dependency_overrides[get_readiness_checks] = lambda: checks
    return app


async def ok(detail: str = "fine") -> str:
    return detail


async def get(app: FastAPI, path: str) -> tuple[int, dict[str, object]]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path)
    return response.status_code, response.json()


async def test_live() -> None:
    code, body = await get(make_app(), "/health/live")
    assert code == 200
    assert body == {"status": "alive"}


async def test_ready_when_all_dependencies_ok() -> None:
    checks: dict[str, Check] = {"postgres": lambda: ok("PostGIS 3.7"), "rabbitmq": ok}
    code, body = await get(make_app(checks), "/health/ready")
    assert code == 200
    assert body == {
        "status": "ready",
        "checks": {
            "postgres": {"ok": True, "detail": "PostGIS 3.7"},
            "rabbitmq": {"ok": True, "detail": "fine"},
        },
    }


async def test_not_ready_reports_failing_dependency() -> None:
    async def missing_postgis() -> str:
        raise DependencyCheckError("PostGIS extension is not installed in the database")

    checks: dict[str, Check] = {"postgres": missing_postgis, "rabbitmq": ok}
    code, body = await get(make_app(checks), "/health/ready")
    assert code == 503
    assert body["status"] == "not_ready"
    assert body["checks"] == {
        "postgres": {"ok": False, "detail": "PostGIS extension is not installed in the database"},
        "rabbitmq": {"ok": True, "detail": "fine"},
    }


async def test_unexpected_errors_do_not_leak_internal_details() -> None:
    async def broken() -> str:
        raise OSError("connect to 10.0.0.5:5432 failed: password=hunter2")

    code, body = await get(make_app({"postgres": broken}), "/health/ready")
    assert code == 503
    assert body["checks"] == {"postgres": {"ok": False, "detail": "unavailable (OSError)"}}


async def test_slow_dependency_times_out() -> None:
    async def slow() -> str:
        await asyncio.sleep(5)
        return "too late"

    code, body = await get(make_app({"rabbitmq": slow}, timeout=0.05), "/health/ready")
    assert code == 503
    assert body["checks"] == {"rabbitmq": {"ok": False, "detail": "timed out"}}
