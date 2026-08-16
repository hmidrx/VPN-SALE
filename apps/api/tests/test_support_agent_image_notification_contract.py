from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0042_support_agent_image_delivery.py"
)


def test_agent_image_migration_extends_existing_payload_free_trigger() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision: str = "0042_support_agent_image"' in source
    assert len("0042_support_agent_image") <= 32
    assert "CREATE OR REPLACE FUNCTION enqueue_support_reply_notification" in source
    assert "NEW.sender_type = 'SUPPORT_AGENT'" in source
    assert "'AGENT_MESSAGE', 'AGENT_ATTACHMENT'" in source
    assert "NEW.visibility = 'PUBLIC'" in source
    assert "conversation.requester_type = 'CUSTOMER'" in source
    assert "ON CONFLICT (message_id) DO NOTHING" in source
    assert "support_reply_notification_outbox" in source
    assert "payload" not in source


def test_agent_image_downgrade_restores_text_only_trigger() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    downgrade = source[source.index("def downgrade()") :]
    assert "_replace_function(\"'AGENT_MESSAGE'\")" in downgrade
    assert "AGENT_ATTACHMENT" not in downgrade
