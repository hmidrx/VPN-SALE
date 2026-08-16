from pathlib import Path

from platform_api.support_notification_models import support_reply_notification_outbox

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0040_support_reply_notifications.py"
)


def test_support_reply_outbox_is_payload_free() -> None:
    columns = set(support_reply_notification_outbox.c.keys())
    assert {"conversation_id", "message_id", "customer_id", "event_reference"} <= columns
    assert {"body", "subject", "payload", "message_text"}.isdisjoint(columns)


def test_migration_enqueues_only_public_customer_agent_replies() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert "NEW.sender_type = 'SUPPORT_AGENT'" in source
    assert "NEW.message_type = 'AGENT_MESSAGE'" in source
    assert "NEW.visibility = 'PUBLIC'" in source
    assert "conversation.requester_type = 'CUSTOMER'" in source
    assert "ON CONFLICT (message_id) DO NOTHING" in source
    assert "AFTER INSERT ON support_messages" in source


def test_migration_downgrade_removes_trigger_before_outbox() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    downgrade = source[source.index("def downgrade()") :]
    assert downgrade.index("DROP TRIGGER") < downgrade.index("op.drop_table(TABLE)")
