import pytest
from vpnsale_domain.identity import validate_customer_password


def password(*parts: str) -> str:
    """Build test inputs at runtime so no credential-like fixture is tracked."""
    return "".join(parts)


def test_customer_password_policy_accepts_unicode_passphrases_unchanged() -> None:
    value = password("correct ", "اسب ", "battery phrase")
    validate_customer_password(value, "customer", min_length=12, max_length=512)


@pytest.mark.parametrize(
    ("value", "username"),
    [
        (password("too", "short"), "customer"),
        (password("password", "1234"), "customer"),
        (password("prefix-", "customer", "-suffix"), "customer"),
    ],
)
def test_customer_password_policy_rejects_targeted_weaknesses(value: str, username: str) -> None:
    with pytest.raises(ValueError):
        validate_customer_password(value, username, min_length=12, max_length=512)


def test_customer_password_policy_rejects_configured_maximum() -> None:
    with pytest.raises(ValueError):
        validate_customer_password("x" * 513, "customer", min_length=12, max_length=512)
