from __future__ import annotations

import html
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from typing import Final
from urllib.parse import urlparse
from uuid import UUID, uuid4

SAFE_URL_SCHEMES: Final = {"https", "mailto"}
MAX_BLOCKS: Final = 120
MAX_BLOCK_TEXT: Final = 8000
PERSIAN_CHARS = str.maketrans({"ي": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه"})
SCRIPT_RE = re.compile(
    r"<\s*(script|iframe|style|object|embed|link|meta)|javascript:|on\w+\s*=", re.I
)
SECRET_RE = re.compile(
    r"(password|secret|token|api[_-]?key|private[_-]?key|\b\d{1,3}(?:\.\d{1,3}){3}\b)", re.I
)


class KnowledgeErrorCode(StrEnum):
    UNSAFE_CONTENT = "KNOWLEDGE_UNSAFE_CONTENT"
    UNSAFE_URL = "KNOWLEDGE_UNSAFE_URL"
    UNKNOWN_BLOCK = "KNOWLEDGE_UNKNOWN_BLOCK"
    INVALID_TRANSITION = "KNOWLEDGE_INVALID_TRANSITION"
    IMMUTABLE_VERSION = "KNOWLEDGE_IMMUTABLE_VERSION"
    PREVIEW_EXPIRED = "KNOWLEDGE_PREVIEW_EXPIRED"
    MEDIA_UNSAFE = "KNOWLEDGE_MEDIA_UNSAFE"
    FLOW_INVALID = "KNOWLEDGE_FLOW_INVALID"
    FEEDBACK_ABUSE = "KNOWLEDGE_FEEDBACK_ABUSE"
    UNPUBLISHED = "KNOWLEDGE_UNPUBLISHED"


class KnowledgeDomainError(ValueError):
    def __init__(self, code: KnowledgeErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


class Audience(StrEnum):
    PUBLIC = "PUBLIC"
    AUTHENTICATED_CUSTOMER = "AUTHENTICATED_CUSTOMER"
    RESELLER = "RESELLER"
    BOTH_CUSTOMER_AND_RESELLER = "BOTH_CUSTOMER_AND_RESELLER"


class ArticleState(StrEnum):
    DRAFT = "DRAFT"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    ROLLED_BACK = "ROLLED_BACK"
    ARCHIVED = "ARCHIVED"
    PUBLISH_FAILED = "PUBLISH_FAILED"


LEGAL_ARTICLE_TRANSITIONS: Final[dict[ArticleState, set[ArticleState]]] = {
    ArticleState.DRAFT: {
        ArticleState.VALIDATION_FAILED,
        ArticleState.READY_FOR_REVIEW,
        ArticleState.APPROVED,
        ArticleState.ARCHIVED,
    },
    ArticleState.VALIDATION_FAILED: {ArticleState.DRAFT, ArticleState.ARCHIVED},
    ArticleState.READY_FOR_REVIEW: {
        ArticleState.APPROVED,
        ArticleState.DRAFT,
        ArticleState.ARCHIVED,
    },
    ArticleState.APPROVED: {
        ArticleState.SCHEDULED,
        ArticleState.PUBLISHING,
        ArticleState.DRAFT,
        ArticleState.ARCHIVED,
    },
    ArticleState.SCHEDULED: {ArticleState.PUBLISHING, ArticleState.APPROVED, ArticleState.ARCHIVED},
    ArticleState.PUBLISHING: {ArticleState.PUBLISHED, ArticleState.PUBLISH_FAILED},
    ArticleState.PUBLISH_FAILED: {ArticleState.APPROVED, ArticleState.ARCHIVED},
    ArticleState.PUBLISHED: {
        ArticleState.SUPERSEDED,
        ArticleState.ROLLED_BACK,
        ArticleState.ARCHIVED,
    },
    ArticleState.SUPERSEDED: {ArticleState.ROLLED_BACK, ArticleState.ARCHIVED},
    ArticleState.ROLLED_BACK: {ArticleState.ARCHIVED},
    ArticleState.ARCHIVED: set(),
}


class BlockType(StrEnum):
    HEADING = "HEADING"
    PARAGRAPH = "PARAGRAPH"
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"
    GALLERY = "GALLERY"
    NUMBERED_STEPS = "NUMBERED_STEPS"
    STEP = "STEP"
    CALLOUT = "CALLOUT"
    WARNING = "WARNING"
    IMPORTANT = "IMPORTANT"
    CODE_BLOCK = "CODE_BLOCK"
    COMMAND = "COMMAND"
    DOWNLOAD = "DOWNLOAD"
    EXTERNAL_LINK = "EXTERNAL_LINK"
    INTERNAL_ARTICLE_LINK = "INTERNAL_ARTICLE_LINK"
    FAQ = "FAQ"
    TROUBLESHOOTING_FLOW = "TROUBLESHOOTING_FLOW"
    COMPATIBILITY_TABLE = "COMPATIBILITY_TABLE"
    APP_DOWNLOAD_REFERENCE = "APP_DOWNLOAD_REFERENCE"
    DIVIDER = "DIVIDER"


class MediaState(StrEnum):
    UPLOADING = "UPLOADING"
    PROCESSING = "PROCESSING"
    READY = "READY"
    REJECTED = "REJECTED"
    QUARANTINED = "QUARANTINED"
    ARCHIVED = "ARCHIVED"
    PROCESSING_FAILED = "PROCESSING_FAILED"


class StatusValue(StrEnum):
    OPERATIONAL = "OPERATIONAL"
    DEGRADED_PERFORMANCE = "DEGRADED_PERFORMANCE"
    PARTIAL_OUTAGE = "PARTIAL_OUTAGE"
    MAJOR_OUTAGE = "MAJOR_OUTAGE"
    MAINTENANCE = "MAINTENANCE"
    UNKNOWN = "UNKNOWN"


class IncidentState(StrEnum):
    DRAFT = "DRAFT"
    INVESTIGATING = "INVESTIGATING"
    IDENTIFIED = "IDENTIFIED"
    MONITORING = "MONITORING"
    RESOLVED = "RESOLVED"


def now_utc() -> datetime:
    return datetime.now(UTC)


def normalize_search_text(value: str) -> str:
    return " ".join(value.translate(PERSIAN_CHARS).casefold().split())[:512]


def reject_unsafe_text(value: str, max_size: int = MAX_BLOCK_TEXT) -> str:
    clean = value.strip()
    if len(clean) > max_size or SCRIPT_RE.search(clean):
        raise KnowledgeDomainError(KnowledgeErrorCode.UNSAFE_CONTENT, "unsafe or oversized content")
    return html.escape(clean, quote=False)


def validate_url(url: str, allowed_hosts: Iterable[str] = ()) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in SAFE_URL_SCHEMES or not parsed.netloc or SCRIPT_RE.search(url):
        raise KnowledgeDomainError(KnowledgeErrorCode.UNSAFE_URL, "unsafe URL")
    hosts = tuple(allowed_hosts)
    if hosts and parsed.hostname not in hosts:
        raise KnowledgeDomainError(KnowledgeErrorCode.UNSAFE_URL, "URL host is not allowlisted")
    return url


@dataclass(frozen=True)
class LocalizedText:
    fa: str
    en: str = ""

    def sanitized(self) -> LocalizedText:
        return LocalizedText(
            reject_unsafe_text(self.fa), reject_unsafe_text(self.en) if self.en else ""
        )


@dataclass(frozen=True)
class KnowledgeContentBlock:
    block_id: UUID
    block_type: BlockType
    order: int
    localized: LocalizedText = field(default_factory=lambda: LocalizedText(fa=""))
    media_ref: str | None = None
    url: str | None = None
    internal_article_code: str | None = None
    children: tuple[KnowledgeContentBlock, ...] = ()
    alt_text: LocalizedText | None = None

    def validate(
        self,
        *,
        published_article_codes: set[str],
        ready_media_refs: set[str],
        allowed_hosts: tuple[str, ...] = (),
    ) -> None:
        if self.order < 0:
            raise KnowledgeDomainError(KnowledgeErrorCode.UNKNOWN_BLOCK, "invalid block order")
        self.localized.sanitized()
        if self.alt_text:
            self.alt_text.sanitized()
        if self.url:
            validate_url(self.url, allowed_hosts)
        if (
            self.block_type in {BlockType.IMAGE, BlockType.VIDEO, BlockType.DOWNLOAD}
            and self.media_ref not in ready_media_refs
        ):
            raise KnowledgeDomainError(KnowledgeErrorCode.MEDIA_UNSAFE, "media is not ready")
        if (
            self.block_type is BlockType.INTERNAL_ARTICLE_LINK
            and self.internal_article_code not in published_article_codes
        ):
            raise KnowledgeDomainError(
                KnowledgeErrorCode.UNPUBLISHED, "internal article link is not published"
            )
        for child in self.children:
            child.validate(
                published_article_codes=published_article_codes,
                ready_media_refs=ready_media_refs,
                allowed_hosts=allowed_hosts,
            )


@dataclass
class KnowledgeArticleVersion:
    version_id: UUID
    article_code: str
    version_number: int
    title: LocalizedText
    summary: LocalizedText
    slug: str
    audience: Audience
    state: ArticleState = ArticleState.DRAFT
    blocks: tuple[KnowledgeContentBlock, ...] = ()
    operating_systems: frozenset[str] = frozenset()
    client_applications: frozenset[str] = frozenset()
    delivery_formats: frozenset[str] = frozenset()
    published_at: datetime | None = None
    optimistic_version: int = 1

    def transition(self, target: ArticleState) -> None:
        if target not in LEGAL_ARTICLE_TRANSITIONS[self.state]:
            raise KnowledgeDomainError(
                KnowledgeErrorCode.INVALID_TRANSITION, "illegal article transition"
            )
        self.state = target
        self.optimistic_version += 1

    def validate_for_publication(
        self, *, published_article_codes: set[str], ready_media_refs: set[str]
    ) -> None:
        if len(self.blocks) > MAX_BLOCKS:
            raise KnowledgeDomainError(KnowledgeErrorCode.UNSAFE_CONTENT, "too many blocks")
        self.title.sanitized()
        self.summary.sanitized()
        for block in sorted(self.blocks, key=lambda b: b.order):
            block.validate(
                published_article_codes=published_article_codes, ready_media_refs=ready_media_refs
            )

    def publish(
        self,
        *,
        at: datetime | None = None,
        published_article_codes: set[str] | None = None,
        ready_media_refs: set[str] | None = None,
    ) -> None:
        if self.state not in {
            ArticleState.APPROVED,
            ArticleState.SCHEDULED,
            ArticleState.PUBLISHING,
        }:
            raise KnowledgeDomainError(
                KnowledgeErrorCode.INVALID_TRANSITION, "article is not publishable"
            )
        self.validate_for_publication(
            published_article_codes=published_article_codes or set(),
            ready_media_refs=ready_media_refs or set(),
        )
        self.state = ArticleState.PUBLISHED
        self.published_at = at or now_utc()
        self.optimistic_version += 1

    def assert_mutable(self) -> None:
        if self.state in {
            ArticleState.PUBLISHED,
            ArticleState.SUPERSEDED,
            ArticleState.ROLLED_BACK,
            ArticleState.ARCHIVED,
        }:
            raise KnowledgeDomainError(
                KnowledgeErrorCode.IMMUTABLE_VERSION, "published history is immutable"
            )

    def clone_as_draft(self) -> KnowledgeArticleVersion:
        return KnowledgeArticleVersion(
            uuid4(),
            self.article_code,
            self.version_number + 1,
            self.title,
            self.summary,
            self.slug,
            self.audience,
            blocks=self.blocks,
            operating_systems=self.operating_systems,
            client_applications=self.client_applications,
            delivery_formats=self.delivery_formats,
        )


@dataclass(frozen=True)
class KnowledgePreviewSession:
    token_hash: str
    version_id: UUID
    actor_id: UUID
    expires_at: datetime

    @classmethod
    def issue(
        cls,
        raw_token: str,
        version_id: UUID,
        actor_id: UUID,
        ttl: timedelta = timedelta(minutes=15),
    ) -> KnowledgePreviewSession:
        return cls(sha256(raw_token.encode()).hexdigest(), version_id, actor_id, now_utc() + ttl)

    def authorize(self, raw_token: str, actor_id: UUID, at: datetime | None = None) -> bool:
        if (
            sha256(raw_token.encode()).hexdigest() != self.token_hash
            or actor_id != self.actor_id
            or (at or now_utc()) >= self.expires_at
        ):
            raise KnowledgeDomainError(
                KnowledgeErrorCode.PREVIEW_EXPIRED, "preview is unauthorized or expired"
            )
        return True


@dataclass(frozen=True)
class EducationalMediaAsset:
    public_ref: str
    claimed_filename: str
    content_type: str
    content: bytes
    state: MediaState = MediaState.UPLOADING

    def inspect(self) -> EducationalMediaAsset:
        signatures = {
            b"\x89PNG": "image/png",
            b"\xff\xd8\xff": "image/jpeg",
            b"%PDF": "application/pdf",
            b"ftyp": "video/mp4",
            b"RIFF": "image/webp",
        }
        if (
            self.content.startswith((b"MZ", b"\x7fELF", b"#!", b"PK\x03\x04"))
            or b"<script" in self.content[:1024].lower()
            or b"<html" in self.content[:1024].lower()
        ):
            return self.with_state(MediaState.QUARANTINED)
        detected = next(
            (
                mime
                for sig, mime in signatures.items()
                if self.content.startswith(sig) or sig in self.content[:16]
            ),
            "text/plain"
            if self.content and all(9 <= b <= 126 or b in (10, 13) for b in self.content[:256])
            else "",
        )
        if detected != self.content_type:
            return self.with_state(MediaState.REJECTED)
        return self.with_state(MediaState.READY)

    def with_state(self, state: MediaState) -> EducationalMediaAsset:
        return EducationalMediaAsset(
            self.public_ref, self.claimed_filename, self.content_type, self.content, state
        )

    @property
    def digest(self) -> str:
        return sha256(self.content).hexdigest()


@dataclass(frozen=True)
class TroubleshootingNode:
    node_id: str
    node_type: str
    text: LocalizedText
    edges: tuple[str, ...] = ()


@dataclass(frozen=True)
class TroubleshootingFlow:
    code: str
    nodes: tuple[TroubleshootingNode, ...]
    start_node_id: str

    def validate(self) -> None:
        by_id = {n.node_id: n for n in self.nodes}
        if self.start_node_id not in by_id or len(by_id) != len(self.nodes) or len(self.nodes) > 80:
            raise KnowledgeDomainError(
                KnowledgeErrorCode.FLOW_INVALID, "invalid flow size or start"
            )
        terminals = {"END_SUCCESS", "END_UNRESOLVED", "SUPPORT_ESCALATION"}

        def walk(node_id: str, seen: set[str], depth: int) -> bool:
            if depth > 20 or node_id in seen:
                return False
            node = by_id[node_id]
            if node.node_type in terminals:
                return True
            return bool(node.edges) and all(
                edge in by_id and walk(edge, seen | {node_id}, depth + 1) for edge in node.edges
            )

        if not walk(self.start_node_id, set(), 0):
            raise KnowledgeDomainError(
                KnowledgeErrorCode.FLOW_INVALID, "every branch must terminate"
            )


@dataclass(frozen=True)
class GuideRecommendation:
    recommended_article_code: str | None
    alternatives: tuple[str, ...]
    reason_codes: tuple[str, ...]


def recommend_guide(
    articles: Iterable[KnowledgeArticleVersion],
    *,
    audience: Audience,
    os_code: str | None = None,
    app_code: str | None = None,
    delivery_format: str | None = None,
) -> GuideRecommendation:
    candidates = [
        a
        for a in articles
        if a.state is ArticleState.PUBLISHED
        and a.audience in {Audience.PUBLIC, audience, Audience.BOTH_CUSTOMER_AND_RESELLER}
    ]
    scored: list[tuple[int, str]] = []
    for article in candidates:
        score = 0
        if os_code and os_code in article.operating_systems:
            score += 4
        if app_code and app_code in article.client_applications:
            score += 3
        if delivery_format and delivery_format in article.delivery_formats:
            score += 2
        scored.append((score, article.article_code))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return GuideRecommendation(
        scored[0][1] if scored else None,
        tuple(code for _, code in scored[1:4]),
        ("PUBLISHED_MATCH",) if scored else ("MISSING_GUIDE",),
    )


@dataclass(frozen=True)
class ArticleFeedback:
    article_code: str
    version_number: int
    actor_key: str
    helpful: bool
    reason: str = ""

    def validate(self) -> None:
        reject_unsafe_text(self.reason, 500)


@dataclass(frozen=True)
class StatusComponent:
    code: str
    name: LocalizedText
    status: StatusValue = StatusValue.UNKNOWN


@dataclass
class StatusIncident:
    incident_id: UUID
    title: LocalizedText
    state: IncidentState = IncidentState.DRAFT
    updates: list[str] = field(default_factory=list)

    def publish_update(self, body: str) -> str:
        safe = reject_unsafe_text(body, 1200)
        if SECRET_RE.search(safe):
            raise KnowledgeDomainError(
                KnowledgeErrorCode.UNSAFE_CONTENT, "incident contains secret-like content"
            )
        event_id = sha256(f"{self.incident_id}:{len(self.updates)}:{safe}".encode()).hexdigest()
        self.updates.append(safe)
        return event_id
