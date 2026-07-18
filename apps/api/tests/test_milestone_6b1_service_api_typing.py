from __future__ import annotations

import pytest
from fastapi import HTTPException

from platform_api.services import snapshot_non_negative_int


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (2, 2),
        ("3", 3),
        (None, 0),
    ],
)
def test_snapshot_non_negative_int_accepts_valid_snapshot_values(
    value: object, expected: int
) -> None:
    assert snapshot_non_negative_int(value, "required_attachment_count", 0) == expected


@pytest.mark.parametrize(
    "value",
    [
        "two",
        True,
        False,
        1.5,
        [1],
        {"count": 1},
        -1,
    ],
)
def test_snapshot_non_negative_int_rejects_invalid_snapshot_values(value: object) -> None:
    with pytest.raises(HTTPException) as exc_info:
        snapshot_non_negative_int(value, "required_attachment_count", 0)
    assert exc_info.value.detail == {
        "code": "SERVICE_ENTITLEMENT_INVALID",
        "field": "required_attachment_count",
    }
