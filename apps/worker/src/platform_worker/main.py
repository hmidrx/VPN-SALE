from __future__ import annotations

import json
import os
import socket
import time

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from platform_api.database import sync_database_url

from .manual_topup_delivery import (
    DeliverySettings,
    ManualTopupDeliveryWorker,
    TelegramDeliveryError,
)
from .order_fulfillment import DisabledProvisioner, OrderFulfillmentWorker
from .real_activator import DatabaseSanaeiActivator
from .real_provisioner import DatabaseSanaeiProvisioner
from .real_service_operation_executor import DatabaseSanaeiServiceOperationExecutor
from .service_activation import DisabledActivator, ServiceActivationWorker
from .service_expiry_notification import ServiceExpiryNotificationWorker
from .service_operation_execution import (
    DisabledServiceOperationExecutor,
    ServiceOperationExecutionWorker,
)
from .service_operation_notification import ServiceOperationNotificationWorker
from .service_usage_sync import ServiceUsageSyncWorker
from .support_reply_delivery import SupportDeliverySettings, SupportReplyDeliveryWorker
from .support_sla_escalation import SupportSlaEscalationWorker


def build_order_provisioner(
    factory: sessionmaker[Session], provider_writes_enabled: bool
) -> DisabledProvisioner | DatabaseSanaeiProvisioner:
    return (
        DatabaseSanaeiProvisioner(factory, True)
        if provider_writes_enabled
        else DisabledProvisioner()
    )


def build_service_activator(
    factory: sessionmaker[Session], provider_writes_enabled: bool
) -> DisabledActivator | DatabaseSanaeiActivator:
    return (
        DatabaseSanaeiActivator(factory, True) if provider_writes_enabled else DisabledActivator()
    )


def build_service_operation_executor(
    factory: sessionmaker[Session], provider_writes_enabled: bool
) -> DisabledServiceOperationExecutor | DatabaseSanaeiServiceOperationExecutor:
    return (
        DatabaseSanaeiServiceOperationExecutor(factory, True)
        if provider_writes_enabled
        else DisabledServiceOperationExecutor()
    )


class BotApiTransport:
    def __init__(self, token: str):
        base = f"https://api.telegram.org/bot{token}"
        self._message_endpoint = f"{base}/sendMessage"
        self._photo_endpoint = f"{base}/sendPhoto"

    @staticmethod
    def _reply_markup(mini_app_url: str) -> dict[str, object]:
        return {"inline_keyboard": [[{"text": "مشاهده درخواست", "web_app": {"url": mini_app_url}}]]}

    @staticmethod
    def _callback_reply_markup(button_text: str, callback_data: str) -> dict[str, object]:
        return {"inline_keyboard": [[{"text": button_text, "callback_data": callback_data}]]}

    def send(self, telegram_user_id: int, text: str, mini_app_url: str) -> None:
        try:
            response = httpx.post(
                self._message_endpoint,
                json={
                    "chat_id": telegram_user_id,
                    "text": text,
                    "reply_markup": self._reply_markup(mini_app_url),
                },
                timeout=10,
            )
            if response.status_code >= 400:
                raise TelegramDeliveryError("telegram delivery failed")
        except httpx.HTTPError as exc:
            raise TelegramDeliveryError("telegram delivery failed") from exc

    def send_callback(
        self,
        telegram_user_id: int,
        text: str,
        button_text: str,
        callback_data: str,
    ) -> None:
        try:
            response = httpx.post(
                self._message_endpoint,
                json={
                    "chat_id": telegram_user_id,
                    "text": text,
                    "reply_markup": self._callback_reply_markup(button_text, callback_data),
                },
                timeout=10,
            )
            if response.status_code >= 400:
                raise TelegramDeliveryError("telegram delivery failed")
        except httpx.HTTPError as exc:
            raise TelegramDeliveryError("telegram delivery failed") from exc

    def send_photo(
        self,
        telegram_user_id: int,
        photo: bytes,
        filename: str,
        media_type: str,
        caption: str,
        mini_app_url: str,
    ) -> None:
        try:
            response = httpx.post(
                self._photo_endpoint,
                data={
                    "chat_id": str(telegram_user_id),
                    "caption": caption,
                    "reply_markup": json.dumps(
                        self._reply_markup(mini_app_url), separators=(",", ":")
                    ),
                },
                files={"photo": (filename, photo, media_type)},
                timeout=15,
            )
            if response.status_code >= 400:
                raise TelegramDeliveryError("telegram delivery failed")
        except httpx.HTTPError as exc:
            raise TelegramDeliveryError("telegram delivery failed") from exc


def main() -> None:
    database = os.environ["VPN_SALE_DATABASE_URL"]
    enabled = os.getenv("VPN_SALE_BOT_ENABLED", "false").lower() == "true"
    token = os.getenv("VPN_SALE_TELEGRAM_BOT_TOKEN", "")
    if enabled and not token:
        raise RuntimeError("enabled notification worker requires a bot token")
    engine = create_engine(sync_database_url(database), pool_pre_ping=True)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    public_app_origin = os.getenv("VPN_SALE_PUBLIC_APP_ORIGIN", "http://localhost:3000")
    delivery_settings = DeliverySettings(enabled, public_app_origin)
    support_delivery_settings = SupportDeliverySettings(
        enabled,
        public_app_origin,
        os.getenv(
            "VPN_SALE_SUPPORT_PRIVATE_UPLOAD_ROOT",
            "/var/lib/vpnsale/private/support",
        ),
    )
    transport = BotApiTransport(token)
    manual_topup = ManualTopupDeliveryWorker(factory, transport, delivery_settings)
    support_reply = SupportReplyDeliveryWorker(factory, transport, support_delivery_settings)
    service_expiry_notifications = ServiceExpiryNotificationWorker(
        factory,
        transport,
        enabled,
    )
    service_operation_notifications = ServiceOperationNotificationWorker(
        factory,
        transport,
        enabled,
    )
    support_sla = SupportSlaEscalationWorker(factory)
    provider_writes_enabled = (
        os.getenv("VPN_SALE_PROVIDER_WRITES_ENABLED", "false").lower() == "true"
    )
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    usage_sync = ServiceUsageSyncWorker(factory, f"usage:{worker_id}")
    provisioner = build_order_provisioner(factory, provider_writes_enabled)
    fulfillment = OrderFulfillmentWorker(factory, provisioner, worker_id)
    activation = ServiceActivationWorker(
        factory,
        build_service_activator(factory, provider_writes_enabled),
        worker_id,
    )
    service_operations = ServiceOperationExecutionWorker(
        factory,
        build_service_operation_executor(factory, provider_writes_enabled),
        worker_id,
    )
    while True:
        processed = 0
        try:
            processed += manual_topup.run_once()
        except Exception:
            print("manual_topup_worker_cycle_failed", flush=True)
        try:
            processed += support_reply.run_once()
        except Exception:
            print("support_reply_worker_cycle_failed", flush=True)
        try:
            processed += support_sla.run_once()
        except Exception:
            print("support_sla_worker_cycle_failed", flush=True)
        try:
            processed += fulfillment.run_once()
        except Exception:
            print("order_fulfillment_worker_cycle_failed", flush=True)
        try:
            processed += activation.run_once()
        except Exception:
            print("service_activation_worker_cycle_failed", flush=True)
        try:
            processed += service_operations.run_once()
        except Exception:
            print("service_operation_worker_cycle_failed", flush=True)
        try:
            processed += usage_sync.run_once()
        except Exception:
            print("service_usage_sync_worker_cycle_failed", flush=True)
        try:
            processed += service_expiry_notifications.run_once()
        except Exception:
            print("service_expiry_notification_worker_cycle_failed", flush=True)
        try:
            processed += service_operation_notifications.run_once()
        except Exception:
            print("service_operation_notification_worker_cycle_failed", flush=True)
        time.sleep(1 if processed else 5)


if __name__ == "__main__":
    main()
