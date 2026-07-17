from vpnsale_domain.configuration import (
    Draft,
    compiled_defaults,
    publish,
    render_template,
    stable_rollout,
    validate_snapshot,
    validate_template,
)


def test_default_snapshot_valid_and_publish_immutable() -> None:
    draft = Draft(reference="draft_test")
    assert draft.validate().ok
    release = publish(draft, None)
    assert release.state == "PUBLISHED"
    assert release.snapshot["schema_version"] == 1


def test_rejects_unsafe_url_secret_and_script() -> None:
    snapshot = compiled_defaults()
    snapshot["brand"] = {
        **snapshot["brand"],
        "support_url": "javascript:alert(1)",
        "tagline": {"fa": "token=abc", "en": "x"},
    }
    result = validate_snapshot(snapshot)
    assert not result.ok
    assert {i.code for i in result.issues} & {
        "url.unsafe_scheme",
        "injection.detected",
        "secret.detected",
    }


def test_template_placeholders_and_escaping() -> None:
    assert not validate_template("telegram.welcome", "Hi {customer.password}").ok
    rendered = render_template(
        "telegram.welcome",
        "Hi {customer_display_name}",
        {"customer_display_name": "<b>A</b>"},
        destination="telegram",
    )
    assert rendered == "Hi &lt;b&gt;A&lt;/b&gt;"


def test_theme_contrast_blocks_publish() -> None:
    snapshot = compiled_defaults()
    snapshot["theme"]["light"]["text_primary_color"] = "#ffffff"
    result = validate_snapshot(snapshot)
    assert not result.ok
    assert "theme.contrast" in {i.code for i in result.issues}


def test_safe_navigation_and_telegram_actions() -> None:
    snapshot = compiled_defaults()
    snapshot["customer_navigation"].append(
        {"code": "BAD", "label": {"fa": "بد", "en": "Bad"}, "destination": "/admin", "order": 9}
    )
    snapshot["telegram_menu"].append(
        {
            "code": "BAD",
            "label": {"fa": "بد", "en": "Bad"},
            "action": "OPEN_SUPPORT",
            "callback_data": "import os",
        }
    )
    result = validate_snapshot(snapshot)
    assert not result.ok
    assert {"navigation.destination", "telegram.action", "telegram.callback"}.issubset(
        {i.code for i in result.issues}
    )


def test_stable_rollout_is_deterministic() -> None:
    values = [stable_rollout("wallet", "opaque-subject", 25) for _ in range(5)]
    assert values == [values[0]] * 5
