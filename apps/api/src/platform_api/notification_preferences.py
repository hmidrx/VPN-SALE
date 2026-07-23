from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .database import get_db_session
from .identity.models import IdentityBase, TelegramAccountModel


class NotificationEventType(StrEnum):
    SERVICE_EXPIRY = "service_expiry"
    LOW_TRAFFIC = "low_traffic"
    PAYMENT = "payment"
    SUPPORT_REPLY = "support_reply"
    ANNOUNCEMENT = "announcement"


class CustomerNotificationPreferenceModel(IdentityBase):
    __tablename__ = "customer_notification_preferences"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    customer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("identity_users.id", ondelete="RESTRICT"), nullable=False
    )
    service_expiry_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    low_traffic_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    payment_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    support_reply_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    announcements_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("customer_id", name="uq_customer_notification_preferences_customer"),
    )


class NotificationPreferenceIdempotencyModel(IdentityBase):
    __tablename__ = "customer_notification_preference_idempotency"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    customer_id: Mapped[str] = mapped_column(String(36), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "customer_id", "idempotency_key", name="uq_customer_notification_pref_idem"
        ),
    )


class NotificationPreferencesOut(BaseModel):
    service_expiry_enabled: bool = True
    low_traffic_enabled: bool = True
    payment_enabled: bool = True
    support_reply_enabled: bool = True
    announcements_enabled: bool = True


class NotificationPreferencePatch(BaseModel):
    key: str
    enabled: bool


router = APIRouter(
    prefix="/api/v1/customer/notification-preferences", tags=["customer-notification-preferences"]
)


def required_customer_id_from_telegram_account(user_id: str | None) -> str:
    if user_id is None:
        raise HTTPException(status_code=404, detail="customer_not_found")
    return user_id


def customer_id_from_telegram(db: Session, telegram_user_id: int) -> str:
    row = db.scalar(
        select(TelegramAccountModel).where(
            TelegramAccountModel.telegram_user_id == telegram_user_id
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="customer_not_found")
    return required_customer_id_from_telegram_account(row.user_id)


def _ensure(db: Session, customer_id: str) -> CustomerNotificationPreferenceModel:
    row = db.scalar(
        select(CustomerNotificationPreferenceModel).where(
            CustomerNotificationPreferenceModel.customer_id == customer_id
        )
    )
    if row:
        return row
    row = CustomerNotificationPreferenceModel(customer_id=customer_id, updated_at=datetime.now(UTC))
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        row = db.scalar(
            select(CustomerNotificationPreferenceModel).where(
                CustomerNotificationPreferenceModel.customer_id == customer_id
            )
        )
        if row is None:
            raise
    return row


def _out(row: CustomerNotificationPreferenceModel) -> NotificationPreferencesOut:
    return NotificationPreferencesOut(
        service_expiry_enabled=row.service_expiry_enabled,
        low_traffic_enabled=row.low_traffic_enabled,
        payment_enabled=row.payment_enabled,
        support_reply_enabled=row.support_reply_enabled,
        announcements_enabled=row.announcements_enabled,
    )


@router.get("/telegram/{telegram_user_id}", response_model=NotificationPreferencesOut)
def get_preferences(
    telegram_user_id: int, db: Annotated[Session, Depends(get_db_session)]
) -> NotificationPreferencesOut:
    return _out(_ensure(db, customer_id_from_telegram(db, telegram_user_id)))


@router.patch("/telegram/{telegram_user_id}", response_model=NotificationPreferencesOut)
def patch_preferences(
    telegram_user_id: int,
    payload: NotificationPreferencePatch,
    db: Annotated[Session, Depends(get_db_session)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
) -> NotificationPreferencesOut:
    customer_id = customer_id_from_telegram(db, telegram_user_id)
    row = _ensure(db, customer_id)
    idem = NotificationPreferenceIdempotencyModel(
        customer_id=customer_id, idempotency_key=idempotency_key, created_at=datetime.now(UTC)
    )
    db.add(idem)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return _out(_ensure(db, customer_id))
    if payload.key not in NotificationPreferencesOut.model_fields:
        raise HTTPException(status_code=400, detail="invalid_preference")
    setattr(row, payload.key, payload.enabled)
    row.updated_at = datetime.now(UTC)
    db.flush()
    return _out(row)


def notification_enabled(
    preferences: NotificationPreferencesOut, event_type: NotificationEventType
) -> bool:
    mapping = {
        NotificationEventType.SERVICE_EXPIRY: preferences.service_expiry_enabled,
        NotificationEventType.LOW_TRAFFIC: preferences.low_traffic_enabled,
        NotificationEventType.PAYMENT: preferences.payment_enabled,
        NotificationEventType.SUPPORT_REPLY: preferences.support_reply_enabled,
        NotificationEventType.ANNOUNCEMENT: preferences.announcements_enabled,
    }
    return mapping[event_type]
