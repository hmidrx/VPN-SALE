from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from vpnsale_domain.resellers import (
    CreditFacility,
    PriceScope,
    PricingRuleKind,
    ResellerPricingRule,
    evaluate_reseller_price,
    render_remark_template,
    require_expected_version,
    require_reseller_transition,
)

from .management import require_perm

admin_router = APIRouter(prefix="/api/v1/admin/management/resellers", tags=["admin-resellers"])
reseller_router = APIRouter(prefix="/api/v1/reseller", tags=["reseller-foundation"])


class ResellerCreateRequest(BaseModel):
    principal_user_id: str
    business_name: str = Field(min_length=1, max_length=180)
    public_brand_label: str = Field(min_length=1, max_length=120)
    settlement_mode: str = Field(pattern="^(PREPAID|CONTROLLED_CREDIT)$")


class LifecycleRequest(BaseModel):
    target_status: str
    expected_version: int
    reason: str = Field(min_length=3, max_length=240)


class PriceSimulationRequest(BaseModel):
    base_price_rial: int = Field(gt=0)
    rule_kind: PricingRuleKind
    amount_rial: int | None = None
    percent_bps: int | None = None
    minimum_price_rial: int = Field(default=0, ge=0)
    minimum_margin_rial: int = Field(default=0, ge=0)
    quantity: int = Field(default=1, gt=0)


class RemarkPreviewRequest(BaseModel):
    template: str = Field(min_length=1, max_length=96)
    values: dict[str, str] = Field(default_factory=dict)


_RESELLERS: dict[str, dict[str, Any]] = {}


def _ref(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(16).replace('-', '').replace('_', '')[:22]}"


@admin_router.get("", dependencies=[Depends(require_perm("resellers.read"))])
def list_resellers() -> dict[str, object]:
    return {"items": list(_RESELLERS.values()), "next_cursor": None}


@admin_router.post("", dependencies=[Depends(require_perm("resellers.manage"))])
def create_reseller(body: ResellerCreateRequest, request: Request) -> dict[str, object]:
    ref = _ref("rsl")
    item: dict[str, Any] = {
        "reseller_reference": ref,
        "principal_user_id": body.principal_user_id,
        "business_name": body.business_name,
        "public_brand_label": body.public_brand_label,
        "status": "DRAFT",
        "settlement_mode": body.settlement_mode,
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "audit": [
            {
                "event_code": "reseller.created",
                "correlation_id": request.headers.get("x-request-id", "local"),
            }
        ],
    }
    _RESELLERS[ref] = item
    return item


@admin_router.post(
    "/{reseller_reference}/lifecycle",
    dependencies=[Depends(require_perm("resellers.manage_status"))],
)
def lifecycle(
    reseller_reference: str, body: LifecycleRequest, request: Request
) -> dict[str, object]:
    item = _RESELLERS.get(reseller_reference)
    if item is None:
        raise HTTPException(404, "reseller not found")
    require_expected_version(int(item["version"]), body.expected_version)
    require_reseller_transition(str(item["status"]), body.target_status)
    item["status"] = body.target_status
    item["version"] = int(item["version"]) + 1
    item.setdefault("audit", []).append(
        {
            "event_code": "reseller.lifecycle",
            "reason": body.reason,
            "correlation_id": request.headers.get("x-request-id", "local"),
        }
    )
    return item


@admin_router.post(
    "/pricing/simulate",
    dependencies=[Depends(require_perm("reseller_price_books.read"))],
)
def simulate_price(body: PriceSimulationRequest) -> dict[str, object]:
    rule = ResellerPricingRule(
        kind=body.rule_kind,
        priority=10,
        scope=PriceScope.PURCHASE,
        exact_amount_rial=body.amount_rial if body.rule_kind == PricingRuleKind.EXACT else None,
        percent_bps=body.percent_bps,
        fixed_discount_rial=body.amount_rial if body.rule_kind != PricingRuleKind.EXACT else None,
        minimum_price_rial=body.minimum_price_rial,
        minimum_margin_rial=body.minimum_margin_rial,
    )
    return evaluate_reseller_price(body.base_price_rial, [rule], body.quantity).__dict__


@reseller_router.get("/profile")
def profile() -> dict[str, object]:
    active = next((r for r in _RESELLERS.values() if r["status"] == "ACTIVE"), None)
    return active or {"status": "UNAVAILABLE"}


@reseller_router.post("/remarks/preview")
def preview_remark(body: RemarkPreviewRequest) -> dict[str, object]:
    return {"remark": render_remark_template(body.template, body.values)}


@reseller_router.post("/credit/reserve-preview")
def reserve_credit_preview(amount_rial: int = 1, limit_rial: int = 1) -> dict[str, object]:
    facility = CreditFacility(
        limit_rial=limit_rial, utilized_rial=0, blocked=False, effective_at=datetime.now(UTC)
    ).reserve(amount_rial)
    return {
        "limit_rial": facility.limit_rial,
        "utilized_rial": facility.utilized_rial,
        "available_rial": facility.limit_rial - facility.utilized_rial,
    }
