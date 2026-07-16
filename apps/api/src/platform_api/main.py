from fastapi import FastAPI, Response, status

from .admin_auth.routes import router as admin_auth_router
from .config import get_settings, validate_security_configuration
from .dependencies import check_database, check_redis
from .logging import configure_logging

configure_logging()
validate_security_configuration(get_settings())
app = FastAPI(title=get_settings().app_name, version=get_settings().version)
app.include_router(admin_auth_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/version")
async def version() -> dict[str, str]:
    settings = get_settings()
    return {"version": settings.version, "environment": settings.environment}


@app.get("/ready")
async def ready(response: Response) -> dict[str, object]:
    checks = {"database": await check_database(), "redis": await check_redis()}
    if not all(checks.values()):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if all(checks.values()) else "not_ready", "checks": checks}


@app.get("/metrics")
async def metrics() -> Response:
    body = (
        "# HELP vpnsale_api_info Milestone 0 API info\n"
        "# TYPE vpnsale_api_info gauge\n"
        'vpnsale_api_info{version="0.0.0-milestone0"} 1\n'
    )
    return Response(content=body, media_type="text/plain; version=0.0.4")
