from fastapi import FastAPI, Response, status

from .admin_auth.routes import router as admin_auth_router
from .catalog import admin_router as admin_catalog_router
from .catalog import customer_router as catalog_router
from .config import get_settings, validate_security_configuration
from .customer_auth.routes import router as customer_auth_router
from .dependencies import check_database, check_redis
from .logging import configure_logging
from .management import public_router as admin_invitation_router
from .management import router as management_router
from .wallet import admin_ledger_router, admin_wallet_router
from .wallet import customer_router as wallet_router

configure_logging()
validate_security_configuration(get_settings())
app = FastAPI(title=get_settings().app_name, version=get_settings().version)
app.include_router(admin_auth_router)
app.include_router(customer_auth_router)
app.include_router(management_router)
app.include_router(catalog_router)
app.include_router(admin_catalog_router)
app.include_router(wallet_router)
app.include_router(admin_wallet_router)
app.include_router(admin_ledger_router)
app.include_router(admin_invitation_router)


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
