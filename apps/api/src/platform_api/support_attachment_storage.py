"""Private, metadata-stripping storage for support image attachments."""

from __future__ import annotations

import hashlib
import io
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from PIL import Image, UnidentifiedImageError

MAX_SUPPORT_ATTACHMENT_BYTES = 5 * 1024 * 1024
ALLOWED_SUPPORT_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
_FORMATS = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "WEBP": ("image/webp", ".webp"),
}
_ASSET_REFERENCE = re.compile(r"^SAT-[0-9a-f]{24}$")


class InvalidSupportAttachment(ValueError):
    """Generic validation failure that is safe to translate into an API error."""


@dataclass(frozen=True)
class StoredSupportAttachment:
    sanitized_sha256: str
    byte_size: int
    media_type: str
    suffix: str


class LocalPrivateSupportAttachmentStorage:
    """Store or read verified support images under opaque asset references."""

    def __init__(
        self,
        root: Path,
        *,
        maximum_bytes: int = MAX_SUPPORT_ATTACHMENT_BYTES,
        dimension_limit: int = 8_192,
        pixel_limit: int = 40_000_000,
        prepare_root: bool = True,
    ) -> None:
        self.root = root.resolve()
        self.maximum_bytes = maximum_bytes
        self.dimension_limit = dimension_limit
        self.pixel_limit = pixel_limit
        if prepare_root:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self.root, 0o700)

    def store(
        self,
        asset_reference: str,
        source: BinaryIO,
        declared_media_type: str,
    ) -> StoredSupportAttachment:
        self._validate_reference(asset_reference)
        if declared_media_type not in ALLOWED_SUPPORT_IMAGE_TYPES:
            raise InvalidSupportAttachment("invalid support attachment")
        raw = self._read_bounded(source)
        try:
            with Image.open(io.BytesIO(raw)) as image:
                image.verify()
            with Image.open(io.BytesIO(raw)) as image:
                media_type, suffix = _FORMATS[image.format or ""]
                if media_type != declared_media_type or getattr(image, "n_frames", 1) != 1:
                    raise InvalidSupportAttachment("invalid support attachment")
                width, height = image.size
                if (
                    width <= 0
                    or height <= 0
                    or max(width, height) > self.dimension_limit
                    or width * height > self.pixel_limit
                ):
                    raise InvalidSupportAttachment("invalid support attachment")
                sanitized = self._sanitize(image, media_type)
        except (KeyError, OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
            raise InvalidSupportAttachment("invalid support attachment") from exc
        if len(sanitized) > self.maximum_bytes:
            raise InvalidSupportAttachment("invalid support attachment")

        destination = self.root / asset_reference
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(destination, flags, 0o600)
        except OSError as exc:
            raise InvalidSupportAttachment("invalid support attachment") from exc
        with os.fdopen(descriptor, "wb") as output:
            output.write(sanitized)
        return StoredSupportAttachment(
            sanitized_sha256=hashlib.sha256(sanitized).hexdigest(),
            byte_size=len(sanitized),
            media_type=media_type,
            suffix=suffix,
        )

    def open(self, asset_reference: str) -> BinaryIO:
        self._validate_reference(asset_reference)
        return (self.root / asset_reference).open("rb")

    def delete(self, asset_reference: str) -> None:
        try:
            self._validate_reference(asset_reference)
        except InvalidSupportAttachment:
            return
        (self.root / asset_reference).unlink(missing_ok=True)

    @staticmethod
    def _validate_reference(asset_reference: str) -> None:
        if (
            _ASSET_REFERENCE.fullmatch(asset_reference) is None
            or Path(asset_reference).name != asset_reference
        ):
            raise InvalidSupportAttachment("invalid support attachment")

    def _read_bounded(self, source: BinaryIO) -> bytes:
        chunks: list[bytes] = []
        total = 0
        while chunk := source.read(min(64 * 1024, self.maximum_bytes + 1 - total)):
            total += len(chunk)
            if total > self.maximum_bytes:
                raise InvalidSupportAttachment("invalid support attachment")
            chunks.append(chunk)
        if not chunks:
            raise InvalidSupportAttachment("invalid support attachment")
        return b"".join(chunks)

    @staticmethod
    def _sanitize(image: Image.Image, media_type: str) -> bytes:
        clean = Image.new("RGB", image.size)
        clean.paste(image.convert("RGB"))
        output = io.BytesIO()
        if media_type == "image/jpeg":
            clean.save(output, format="JPEG", quality=90, optimize=True)
        elif media_type == "image/png":
            clean.save(output, format="PNG", optimize=True)
        else:
            clean.save(output, format="WEBP", quality=90, method=6)
        return output.getvalue()
