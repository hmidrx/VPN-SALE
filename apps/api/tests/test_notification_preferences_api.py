from __future__ import annotations

import pytest
from fastapi import HTTPException

from platform_api.notification_preferences import required_customer_id_from_telegram_account


def test_required_customer_id_from_telegram_account_returns_expected_str() -> None:
    customer_id = "11111111-1111-4111-8111-111111111111"

    assert required_customer_id_from_telegram_account(customer_id) == customer_id


def test_required_customer_id_from_telegram_account_null_is_typed_not_found() -> None:
    with pytest.raises(HTTPException) as exc_info:
        required_customer_id_from_telegram_account(None)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "customer_not_found"
    assert "Traceback" not in str(exc_info.value.detail)
