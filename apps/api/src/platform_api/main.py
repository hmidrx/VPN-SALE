from fastapi import APIRouter, FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.datastructures import Headers

from .admin_auth.routes import router as admin_auth_router
from .catalog import admin_router as admin_catalog_router
from .catalog import customer_router as catalog_router
from .config import Settings, get_settings
from .configuration import admin_router as admin_configuration_router
from .configuration import public_router as runtime_configuration_router
from .customer_admin import router as admin_customer_router
from .customer_auth.routes import account_linking_router, password_login_router, registration_router
from .customer_auth.routes import router as customer_auth_router
from .customer_support_attachments import router as customer_web_support_attachment_router
from .customer_support_csat import router as customer_web_support_csat_router
from .customer_support_read_state import router as customer_web_support_read_state_router
from .customer_support_runtime import router as customer_web_support_runtime_router
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
from .manual_topups import admin_router as admin_manual_topup_router
from .manual_topups import customer_router as customer_manual_topup_router
from .operations import assert_startup_configuration
from .operations import router as operations_router
from .ops_observability import router as admin_ops_observability_router
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
from .support_admin_runtime import router as admin_support_runtime_router
from .support_attachments_runtime import admin_router as admin_support_attachment_router
from .support_attachments_runtime import telegram_router as telegram_support_attachment_router
from .support_pagination_runtime import admin_router as admin_support_pagination_router
from .support_pagination_runtime import telegram_router as telegram_support_pagination_router
from .support_productivity_runtime import router as admin_support_productivity_router
from .support_sla_admin import router as admin_support_sla_router
from .telegram_account_internal import router as telegram_account_internal_router
from .telegram_delivery_internal import router as telegram_delivery_internal_router
from .telegram_internal import router as telegram_internal_router
from .telegram_operator_internal import router as telegram_operator_internal_router
from .telegram_purchase_native_internal import router as telegram_purchase_native_internal_router
from .telegram_service_management_internal import (
    router as telegram_service_management_internal_router,
)
from .telegram_service_operation_payment_internal import (
    router as telegram_service_operation_payment_internal_router,
)
from .telegram_service_operation_status_internal import (
    router as telegram_service_operation_status_internal_router,
)
from .telegram_support_csat_internal import router as telegram_support_csat_internal_router
from .telegram_support_internal import router as telegram_support_internal_router
from .telegram_topup_destination_internal import (
    router as telegram_topup_destination_internal_router,
)
from .usage import admin_router as admin_usage_router
from .usage import anomaly_router as admin_usage_anomaly_router
from .usage import automation_router as admin_lifecycle_automation_router
from .usage import customer_router as customer_usage_router
from .usage import policy_router as admin_usage_policy_router
from .usage import reseller_router as reseller_usage_router
from .wallet import admin_ledger_router, admin_wallet_router
from .wallet import customer_router as wallet_router

system_router = APIRouter()


class FirstPartyCORSMiddleware(CORSMiddleware):
    """Avoid advertising credential support to origins outside the allowlist."""

    def preflight_response(self, request_headers: Headers) -> Response:
        response = super().preflight_response(request_headers)
        origin = request_headers["origin"]
        if not self.is_allowed_origin(origin=origin):
            del response.headers["access-control-allow-credentials"]
        return response


@system_router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "alive"}


@system_router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@system_router.get("/version")
async def version() -> dict[str, str]:
    settings = get_settings()
    return {
        "version": settings.version,
        "environment": settings.environment,
        "schema_revision": __import__("os").getenv("VPN_SALE_SCHEMA_REVISION", "unknown"),
    }


@system_router.get("/ready")
async def ready(response: Response) -> dict[str, object]:
    checks = {"database": await check_database(), "redis": await check_redis()}
    if not all(checks.values()):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if all(checks.values()) else "not_ready", "checks": checks}


@system_router.get("/metrics")
async def metrics() -> Response:
    body = (
        "# HELP vpnsale_api_info Milestone 0 API info\n"
        "# TYPE vpnsale_api_info gauge\n"
        'vpnsale_api_info{version="0.0.0-milestone0"} 1\n'
    )
    return Response(content=body, media_type="text/plain; version=0.0.4")


def create_app(settings: Settings) -> FastAPI:
    configure_logging()
    assert_startup_configuration(settings)
    application = FastAPI(title=settings.app_name, version=settings.version)
    application.add_middleware(
        FirstPartyCORSMiddleware,
        allow_origins=[origin.rstrip("/") for origin in settings.cors_allowed_origins],
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Request-ID",
            "X-Correlation-ID",
            "X-CSRF-Token",
            "X-VPN-Sale-Client",
            "Idempotency-Key",
        ],
        expose_headers=["Retry-After", "X-Request-ID"],
    )
    routers = [
        admin_auth_router,
        customer_auth_router,
        customer_web_support_runtime_router,
        customer_web_support_attachment_router,
        customer_web_support_csat_router,
        customer_web_support_read_state_router,
        management_router,
        catalog_router,
        admin_catalog_router,
        wallet_router,
        order_router,
        payment_router,
        admin_order_router,
        admin_invoice_router,
        admin_checkout_router,
        admin_wallet_payment_router,
        admin_wallet_reservation_router,
        admin_outbox_router,
        admin_commerce_router,
        admin_payment_router,
        admin_reseller_router,
        reseller_router,
        payment_webhook_router,
        admin_wallet_router,
        admin_customer_router,
        customer_manual_topup_router,
        admin_manual_topup_router,
        admin_ledger_router,
        admin_invitation_router,
        runtime_configuration_router,
        admin_configuration_router,
        admin_support_runtime_router,
        admin_support_pagination_router,
        admin_support_attachment_router,
        admin_support_sla_router,
        admin_support_productivity_router,
        knowledge_router,
        admin_knowledge_router,
        status_router,
        admin_status_router,
        admin_service_router,
        customer_service_router,
        admin_allocation_router,
        admin_service_reconciliation_router,
        admin_service_operation_router,
        admin_service_migration_router,
        customer_service_migration_router,
        reseller_service_migration_router,
        admin_failover_router,
        admin_orphan_router,
        customer_service_operation_router,
        reseller_service_operation_router,
        admin_delivery_router,
        customer_delivery_router,
        subscription_router,
        customer_usage_router,
        reseller_usage_router,
        admin_usage_router,
        admin_usage_policy_router,
        admin_usage_anomaly_router,
        admin_lifecycle_automation_router,
        operations_router,
        admin_ops_observability_router,
        admin_fleet_router,
        customer_fleet_router,
        reseller_fleet_router,
        system_router,
        telegram_internal_router,
        telegram_operator_internal_router,
        telegram_purchase_native_internal_router,
        telegram_topup_destination_internal_router,
        telegram_service_management_internal_router,
        telegram_service_operation_payment_internal_router,
        telegram_service_operation_status_internal_router,
        telegram_delivery_internal_router,
        telegram_account_internal_router,
        telegram_support_internal_router,
        telegram_support_pagination_router,
        telegram_support_attachment_router,
        telegram_support_csat_internal_router,
    ]
    for api_router in routers:
        application.include_router(api_router)
    if settings.public_account_registration_enabled:
        application.include_router(registration_router)
    if settings.password_account_login_enabled:
        application.include_router(password_login_router)
    if settings.telegram_account_linking_enabled:
        application.include_router(account_linking_router)
    application.dependency_overrides[get_settings] = lambda: settings
    return application


app = create_app(get_settings())
