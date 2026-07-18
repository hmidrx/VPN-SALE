from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field
from vpnsale_domain.knowledge_status import (
    ArticleState,
    Audience,
    BlockType,
    EducationalMediaAsset,
    IncidentState,
    KnowledgeArticleVersion,
    KnowledgeContentBlock,
    KnowledgeDomainError,
    LocalizedText,
    StatusComponent,
    StatusIncident,
    StatusValue,
    normalize_search_text,
    recommend_guide,
)

public_router = APIRouter(prefix="/api/v1/education", tags=["education"])
admin_router = APIRouter(prefix="/api/v1/admin/knowledge", tags=["admin-knowledge"])
status_router = APIRouter(prefix="/api/v1/status", tags=["status"])
admin_status_router = APIRouter(prefix="/api/v1/admin/status", tags=["admin-status"])

_READY_MEDIA = {"demo-image"}
_ARTICLES: dict[str, KnowledgeArticleVersion] = {}
_COMPONENTS: dict[str, StatusComponent] = {
    code: StatusComponent(code, LocalizedText(fa=name, en=name), StatusValue.UNKNOWN)
    for code, name in {
        "customer_web": "Customer Website",
        "telegram_mini_app": "Telegram Mini App",
        "telegram_bot": "Telegram Bot",
        "admin_panel": "Admin Panel",
        "reseller_panel": "Reseller Panel",
        "api": "API",
        "payments": "Payments",
        "support": "Support",
    }.items()
}
_INCIDENTS: dict[str, StatusIncident] = {}


class LocalizedPayload(BaseModel):
    fa: str = Field(max_length=500)
    en: str = Field(default="", max_length=500)


class BlockPayload(BaseModel):
    block_type: BlockType
    order: int = Field(ge=0, le=1000)
    text: LocalizedPayload
    media_ref: str | None = Field(default=None, max_length=100)
    url: str | None = Field(default=None, max_length=500)
    alt_text: LocalizedPayload | None = None


class ArticleDraftPayload(BaseModel):
    article_code: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,80}$")
    title: LocalizedPayload
    summary: LocalizedPayload
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,100}$")
    audience: Audience
    operating_systems: list[str] = Field(default_factory=list, max_length=20)
    client_applications: list[str] = Field(default_factory=list, max_length=20)
    delivery_formats: list[str] = Field(default_factory=list, max_length=20)
    blocks: list[BlockPayload] = Field(default_factory=list, max_length=120)


class FeedbackPayload(BaseModel):
    helpful: bool
    reason: str = Field(default="", max_length=500)


class IncidentPayload(BaseModel):
    title: LocalizedPayload
    initial_update: str = Field(max_length=1200)


def _lt(payload: LocalizedPayload) -> LocalizedText:
    return LocalizedText(fa=payload.fa, en=payload.en)


def _public_article(article: KnowledgeArticleVersion) -> dict[str, object]:
    return {
        "article_code": article.article_code,
        "version": article.version_number,
        "title": article.title,
        "summary": article.summary,
        "slug": article.slug,
        "audience": article.audience,
        "blocks": article.blocks,
        "published_at": article.published_at,
    }


@admin_router.post("/drafts")
def create_draft(payload: ArticleDraftPayload) -> dict[str, object]:
    blocks = tuple(
        KnowledgeContentBlock(
            uuid4(),
            b.block_type,
            b.order,
            _lt(b.text),
            media_ref=b.media_ref,
            url=b.url,
            alt_text=_lt(b.alt_text) if b.alt_text else None,
        )
        for b in payload.blocks
    )
    article = KnowledgeArticleVersion(
        uuid4(),
        payload.article_code,
        1,
        _lt(payload.title),
        _lt(payload.summary),
        payload.slug,
        payload.audience,
        blocks=blocks,
        operating_systems=frozenset(payload.operating_systems),
        client_applications=frozenset(payload.client_applications),
        delivery_formats=frozenset(payload.delivery_formats),
    )
    _ARTICLES[payload.article_code] = article
    return {
        "article_code": article.article_code,
        "state": article.state,
        "version": article.version_number,
    }


@admin_router.post("/articles/{article_code}/publish")
def publish_article(article_code: str) -> dict[str, object]:
    article = _ARTICLES.get(article_code)
    if article is None:
        raise HTTPException(404, "article not found")
    try:
        if article.state is ArticleState.DRAFT:
            article.transition(ArticleState.APPROVED)
        article.publish(ready_media_refs=_READY_MEDIA)
    except KnowledgeDomainError as exc:
        raise HTTPException(422, exc.code) from exc
    return {
        "article_code": article.article_code,
        "state": article.state,
        "published_at": article.published_at,
    }


@public_router.get("/articles/{article_code}")
def get_article(article_code: str) -> dict[str, object]:
    article = _ARTICLES.get(article_code)
    if article is None or article.state is not ArticleState.PUBLISHED:
        raise HTTPException(404, "published article not found")
    return _public_article(article)


@public_router.get("/search")
def search(q: str = "", audience: Audience = Audience.PUBLIC) -> dict[str, object]:
    query = normalize_search_text(q[:120])
    results: list[dict[str, object]] = []
    for article in _ARTICLES.values():
        haystack = normalize_search_text(f"{article.title.fa} {article.summary.fa} {article.slug}")
        if (
            article.state is ArticleState.PUBLISHED
            and article.audience in {Audience.PUBLIC, audience, Audience.BOTH_CUSTOMER_AND_RESELLER}
            and (not query or query in haystack)
        ):
            results.append(_public_article(article))
    return {
        "results": results[:25],
        "query_normalized": query,
        "empty_suggestions": [] if results else ["categories"],
    }


@public_router.get("/recommendations")
def recommendations(
    audience: Audience = Audience.PUBLIC,
    os_code: str | None = None,
    app_code: str | None = None,
    delivery_format: str | None = None,
) -> dict[str, object]:
    result = recommend_guide(
        _ARTICLES.values(),
        audience=audience,
        os_code=os_code,
        app_code=app_code,
        delivery_format=delivery_format,
    )
    return result.__dict__


@public_router.post("/articles/{article_code}/feedback")
def article_feedback(article_code: str, payload: FeedbackPayload) -> dict[str, object]:
    article = _ARTICLES.get(article_code)
    if article is None or article.state is not ArticleState.PUBLISHED:
        raise HTTPException(404, "published article not found")
    if "<script" in payload.reason.lower():
        raise HTTPException(422, "unsafe feedback")
    return {
        "accepted": True,
        "article_code": article_code,
        "version": article.version_number,
        "aggregate_mutated_publication": False,
    }


@admin_router.post("/media/inspect")
def inspect_media(content_type: str, body: bytes = b"") -> dict[str, object]:
    inspected = EducationalMediaAsset("upload", "upload.bin", content_type, body).inspect()
    return {"state": inspected.state, "digest": inspected.digest}


@status_router.get("/summary")
def public_status(response: Response) -> dict[str, object]:
    response.headers["Cache-Control"] = "public, max-age=30"
    response.headers["ETag"] = 'W/"status-m5f-unknown"'
    active = [i for i in _INCIDENTS.values() if i.state is not IncidentState.RESOLVED]
    return {
        "overall_status": "UNKNOWN"
        if any(c.status is StatusValue.UNKNOWN for c in _COMPONENTS.values())
        else "OPERATIONAL",
        "components": list(_COMPONENTS.values()),
        "active_incidents": active,
        "uptime_percentages": None,
        "vpn_components": [],
    }


@admin_status_router.post("/incidents")
def create_incident(payload: IncidentPayload) -> dict[str, object]:
    incident = StatusIncident(uuid4(), _lt(payload.title), IncidentState.INVESTIGATING)
    try:
        notification_key = incident.publish_update(payload.initial_update)
    except KnowledgeDomainError as exc:
        raise HTTPException(422, exc.code) from exc
    _INCIDENTS[str(incident.incident_id)] = incident
    return {
        "incident_id": str(incident.incident_id),
        "state": incident.state,
        "notification_key": notification_key,
        "created_at": datetime.now(UTC),
    }
