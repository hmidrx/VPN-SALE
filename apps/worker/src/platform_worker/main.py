from __future__ import annotations

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


class BotApiTransport:
    def __init__(self, token: str):
        self._endpoint = f"https://api.telegram.org/bot{token}/sendMessage"

    def send(self, telegram_user_id: int, text: str, mini_app_url: str) -> None:
        try:
            response = httpx.post(
                self._endpoint,
                json={
                    "chat_id": telegram_user_id,
                    "text": text,
                    "reply_markup": {
                        "inline_keyboard": [
                            [{"text": "مشاهده درخواست", "web_app": {"url": mini_app_url}}]
                        ]
                    },
                },
                timeout=10,
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
    worker = ManualTopupDeliveryWorker(
        factory,
        BotApiTransport(token),
        DeliverySettings(enabled, os.getenv("VPN_SALE_PUBLIC_APP_ORIGIN", "http://localhost:3000")),
    )
    fulfillment = OrderFulfillmentWorker(
        factory, DisabledProvisioner(), f"{socket.gethostname()}:{os.getpid()}"
    )
    while True:
        processed = 0
        try:
            processed += worker.run_once()
        except Exception:
            # A responsibility is isolated so its next poll remains available. Log only type.
            print("manual_topup_worker_cycle_failed", flush=True)
        try:
            processed += fulfillment.run_once()
        except Exception:
            print("order_fulfillment_worker_cycle_failed", flush=True)
        time.sleep(1 if processed else 5)


if __name__ == "__main__":
    main()
