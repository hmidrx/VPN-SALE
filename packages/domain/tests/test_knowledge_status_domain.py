from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from vpnsale_domain.knowledge_status import (
    ArticleState,
    Audience,
    BlockType,
    EducationalMediaAsset,
    IncidentState,
    KnowledgeArticleVersion,
    KnowledgeContentBlock,
    KnowledgeDomainError,
    KnowledgePreviewSession,
    LocalizedText,
    MediaState,
    StatusComponent,
    StatusIncident,
    StatusValue,
    TroubleshootingFlow,
    TroubleshootingNode,
    normalize_search_text,
    recommend_guide,
)


def tutorial() -> KnowledgeArticleVersion:
    return KnowledgeArticleVersion(
        version_id=uuid4(),
        article_code="android-safe-guide",
        version_number=1,
        title=LocalizedText(fa="آموزش امن اندروید"),
        summary=LocalizedText(fa="راهنمای نصب آموزشی"),
        slug="android-safe-guide",
        audience=Audience.AUTHENTICATED_CUSTOMER,
        state=ArticleState.APPROVED,
        blocks=(
            KnowledgeContentBlock(uuid4(), BlockType.HEADING, 1, LocalizedText(fa="شروع")),
            KnowledgeContentBlock(
                uuid4(), BlockType.WARNING, 2, LocalizedText(fa="از منابع ناشناس استفاده نکنید")
            ),
            KnowledgeContentBlock(
                uuid4(),
                BlockType.IMAGE,
                3,
                LocalizedText(fa="تصویر"),
                media_ref="m_1",
                alt_text=LocalizedText(fa="نمای برنامه"),
            ),
        ),
        operating_systems=frozenset({"android"}),
        client_applications=frozenset({"approved-app"}),
        delivery_formats=frozenset({"manual"}),
    )


def test_published_article_is_immutable_and_clone_edit_creates_draft() -> None:
    article = tutorial()
    article.publish(at=datetime(2026, 7, 18, tzinfo=UTC), ready_media_refs={"m_1"})
    assert article.state is ArticleState.PUBLISHED
    with pytest.raises(KnowledgeDomainError):
        article.assert_mutable()
    draft = article.clone_as_draft()
    assert draft.state is ArticleState.DRAFT
    assert draft.version_number == 2


def test_safe_block_editor_rejects_html_script_and_unready_media() -> None:
    article = tutorial()
    bad = KnowledgeContentBlock(
        uuid4(), BlockType.PARAGRAPH, 4, LocalizedText(fa="<script>x</script>")
    )
    article.blocks = article.blocks + (bad,)
    with pytest.raises(KnowledgeDomainError):
        article.publish(ready_media_refs={"m_1"})
    article = tutorial()
    with pytest.raises(KnowledgeDomainError):
        article.publish(ready_media_refs=set())


def test_preview_is_actor_scoped_and_short_lived() -> None:
    actor_id = uuid4()
    session = KnowledgePreviewSession.issue("raw-preview", uuid4(), actor_id, timedelta(seconds=1))
    assert session.authorize("raw-preview", actor_id, datetime.now(UTC))
    with pytest.raises(KnowledgeDomainError):
        session.authorize("raw-preview", actor_id, datetime.now(UTC) + timedelta(minutes=1))
    with pytest.raises(KnowledgeDomainError):
        session.authorize("raw-preview", uuid4())


def test_media_inspection_uses_content_not_filename() -> None:
    assert (
        EducationalMediaAsset("m_1", "photo.png", "image/png", b"\x89PNGdata").inspect().state
        is MediaState.READY
    )
    assert (
        EducationalMediaAsset("m_2", "video.mp4", "video/mp4", b"MZ executable").inspect().state
        is MediaState.QUARANTINED
    )
    assert (
        EducationalMediaAsset("m_3", "safe.png", "image/png", b"%PDF-1.7").inspect().state
        is MediaState.REJECTED
    )


def test_troubleshooting_flow_must_be_finite_and_terminal() -> None:
    flow = TroubleshootingFlow(
        "flow-1",
        (
            TroubleshootingNode(
                "start", "QUESTION", LocalizedText(fa="مشکل حل شد؟"), ("no", "yes")
            ),
            TroubleshootingNode("no", "SUPPORT_ESCALATION", LocalizedText(fa="ارسال به پشتیبانی")),
            TroubleshootingNode("yes", "END_SUCCESS", LocalizedText(fa="پایان")),
        ),
        "start",
    )
    flow.validate()
    bad = TroubleshootingFlow(
        "bad", (TroubleshootingNode("a", "QUESTION", LocalizedText(fa="?"), ("a",)),), "a"
    )
    with pytest.raises(KnowledgeDomainError):
        bad.validate()


def test_persian_search_normalization_and_context_recommendation() -> None:
    article = tutorial()
    article.publish(ready_media_refs={"m_1"})
    assert normalize_search_text("كاربرد يک راهنما") == "کاربرد یک راهنما"
    result = recommend_guide(
        [article],
        audience=Audience.AUTHENTICATED_CUSTOMER,
        os_code="android",
        app_code="approved-app",
        delivery_format="manual",
    )
    assert result.recommended_article_code == "android-safe-guide"
    assert result.reason_codes == ("PUBLISHED_MATCH",)


def test_status_components_default_unknown_and_incidents_hide_secrets() -> None:
    component = StatusComponent("api", LocalizedText(fa="API"))
    assert component.status is StatusValue.UNKNOWN
    incident = StatusIncident(uuid4(), LocalizedText(fa="اختلال API"), IncidentState.INVESTIGATING)
    event_id = incident.publish_update("در حال بررسی هستیم")
    assert len(event_id) == 64
    with pytest.raises(KnowledgeDomainError):
        incident.publish_update("token=secret host 10.0.0.1")
