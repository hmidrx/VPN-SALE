from fastapi import FastAPI, Response, status

from .admin_auth.routes import router as admin_auth_router
from .catalog import admin_router as admin_catalog_router
from .catalog import customer_router as catalog_router
from .config import get_settings
from .configuration import admin_router as admin_configuration_router
from .configuration import public_router as runtime_configuration_router
from .customer_admin import router as admin_customer_router
from .customer_auth.routes import router as customer_auth_router
from .delivery import admin_router as admin_delivery_router
from .delivery import customer_router as customer_delivery_router
from .delivery import public_router as subscription_router
from .dependencies import check_database, check_redis
from .fleet import admin_router as admin_fleet_router
from .fleet import customer_router as customer_fleet_router
from .fleet import reseller_router as reseller_fleet_router
from .knowledge_status import admin_router as admin_knowledge_router
from .knowledge_status import admin_status_router, status_router
from .knowledge_status import public_router as knowledge_router
from .logging import configure_logging
from .management import public_router as admin_invitation_router
from .management import router as management_router
from .notification_preferences import router as customer_notification_preferences_router
from .operations import assert_startup_configuration
from .operations import router as operations_router
from .orders import (
    admin_checkout_router,
    admin_commerce_router,
    admin_invoice_router,
    admin_outbox_router,
    admin_wallet_payment_router,
    admin_wallet_reservation_router,
)
from .orders import admin_router as admin_order_router
from .orders import customer_router as order_router
from .payments import admin_router as admin_payment_router
from .payments import customer_router as payment_router
from .payments import webhook_router as payment_webhook_router
from .resellers import admin_router as admin_reseller_router
from .resellers import reseller_router
from .service_migrations import admin_router as admin_service_migration_router
from .service_migrations import customer_router as customer_service_migration_router
from .service_migrations import failover_router as admin_failover_router
from .service_migrations import orphan_router as admin_orphan_router
from .service_migrations import reseller_router as reseller_service_migration_router
from .service_operations import admin_router as admin_service_operation_router
from .service_operations import customer_router as customer_service_operation_router
from .service_operations import reseller_router as reseller_service_operation_router
from .services import admin_router as admin_service_router
from .services import allocation_router as admin_allocation_router
from .services import customer_router as customer_service_router
from .services import reconciliation_router as admin_service_reconciliation_router
from .support import admin_router as admin_support_router
from .support import customer_router as customer_support_router
from .support import reseller_router as reseller_support_router
from .usage import admin_router as admin_usage_router
from .usage import anomaly_router as admin_usage_anomaly_router
from .usage import automation_router as admin_lifecycle_automation_router
from .usage import customer_router as customer_usage_router
from .usage import policy_router as admin_usage_policy_router
from .usage import reseller_router as reseller_usage_router
from .wallet import admin_ledger_router, admin_wallet_router
from .wallet import customer_router as wallet_router

configure_logging()
assert_startup_configuration(get_settings())
app = FastAPI(title=get_settings().app_name, version=get_settings().version)
app.include_router(admin_auth_router)
app.include_router(customer_auth_router)
app.include_router(management_router)
app.include_router(catalog_router)
app.include_router(admin_catalog_router)
app.include_router(wallet_router)
app.include_router(order_router)
app.include_router(customer_notification_preferences_router)
app.include_router(payment_router)
app.include_router(admin_order_router)
app.include_router(admin_invoice_router)
app.include_router(admin_checkout_router)
app.include_router(admin_wallet_payment_router)
app.include_router(admin_wallet_reservation_router)
app.include_router(admin_outbox_router)
app.include_router(admin_commerce_router)
app.include_router(admin_payment_router)
app.include_router(admin_reseller_router)
app.include_router(reseller_router)
app.include_router(payment_webhook_router)
app.include_router(admin_wallet_router)
app.include_router(admin_customer_router)
app.include_router(admin_ledger_router)
app.include_router(admin_invitation_router)
app.include_router(runtime_configuration_router)
app.include_router(admin_configuration_router)
app.include_router(customer_support_router)
app.include_router(reseller_support_router)
app.include_router(admin_support_router)
app.include_router(knowledge_router)
app.include_router(admin_knowledge_router)
app.include_router(status_router)
app.include_router(admin_status_router)
app.include_router(admin_service_router)
app.include_router(customer_service_router)
app.include_router(admin_allocation_router)
app.include_router(admin_service_reconciliation_router)
app.include_router(admin_service_operation_router)
app.include_router(admin_service_migration_router)
app.include_router(customer_service_migration_router)
app.include_router(reseller_service_migration_router)
app.include_router(admin_failover_router)
app.include_router(admin_orphan_router)
app.include_router(customer_service_operation_router)
app.include_router(reseller_service_operation_router)
app.include_router(admin_delivery_router)
app.include_router(customer_delivery_router)
app.include_router(subscription_router)
app.include_router(customer_usage_router)
app.include_router(reseller_usage_router)
app.include_router(admin_usage_router)
app.include_router(admin_usage_policy_router)
app.include_router(admin_usage_anomaly_router)
app.include_router(admin_lifecycle_automation_router)
app.include_router(operations_router)
app.include_router(admin_fleet_router)
app.include_router(customer_fleet_router)
app.include_router(reseller_fleet_router)


def _prometheus_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


@app.get("/live")
async def live() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/version")
async def version() -> dict[str, str]:
    settings = get_settings()
    return {
        "version": settings.version,
        "environment": settings.environment,
        "schema_revision": __import__("os").getenv("VPN_SALE_SCHEMA_REVISION", "unknown"),
    }


@app.get("/ready")
async def ready(response: Response) -> dict[str, object]:
    checks = {"database": await check_database(), "redis": await check_redis()}
    if not all(checks.values()):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if all(checks.values()) else "not_ready", "checks": checks}


@app.get("/metrics")
async def metrics() -> Response:
    version_label = _prometheus_label_value(get_settings().version)
    body = (
        "# HELP vpnsale_api_info VPN-SALE API build information\n"
        "# TYPE vpnsale_api_info gauge\n"
        f'vpnsale_api_info{{version="{version_label}"}} 1\n'
    )
    return Response(content=body, media_type="text/plain; version=0.0.4")
