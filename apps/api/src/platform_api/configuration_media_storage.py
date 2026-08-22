"""Sanitized, opaque public storage for owner-managed brand images."""

from __future__ import annotations

import hashlib
import io
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BRAND_IMAGE_BYTES = 2 * 1024 * 1024
ALLOWED_BRAND_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
_REFERENCE = re.compile(r"^BRAND-[0-9a-f]{24}$")


class InvalidBrandImage(ValueError):
    """Safe validation failure for a public brand image."""


@dataclass(frozen=True)
class StoredBrandImage:
    digest: str
    byte_size: int
    width: int
    height: int
    media_type: str = "image/webp"


class LocalBrandMediaStorage:
    """Keep sanitized public brand images under unguessable opaque references."""

    def __init__(
        self,
        root: Path,
        *,
        maximum_bytes: int = MAX_BRAND_IMAGE_BYTES,
        dimension_limit: int = 4096,
        pixel_limit: int = 16_000_000,
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
        reference: str,
        source: BinaryIO,
        declared_media_type: str,
    ) -> StoredBrandImage:
        self._validate_reference(reference)
        if declared_media_type not in ALLOWED_BRAND_IMAGE_TYPES:
            raise InvalidBrandImage("invalid brand image")
        raw = self._read_bounded(source)
        try:
            with Image.open(io.BytesIO(raw)) as candidate:
                candidate.verify()
            with Image.open(io.BytesIO(raw)) as image:
                if getattr(image, "n_frames", 1) != 1:
                    raise InvalidBrandImage("invalid brand image")
                width, height = image.size
                if (
                    width <= 0
                    or height <= 0
                    or max(width, height) > self.dimension_limit
                    or width * height > self.pixel_limit
                ):
                    raise InvalidBrandImage("invalid brand image")
                clean = ImageOps.exif_transpose(image)
                clean.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
                output = io.BytesIO()
                clean.convert("RGBA").save(output, format="WEBP", lossless=True, method=6)
                sanitized = output.getvalue()
                stored_width, stored_height = clean.size
        except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
            raise InvalidBrandImage("invalid brand image") from exc
        if not sanitized or len(sanitized) > self.maximum_bytes:
            raise InvalidBrandImage("invalid brand image")
        destination = self.path(reference)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(destination, flags, 0o600)
        except OSError as exc:
            raise InvalidBrandImage("invalid brand image") from exc
        with os.fdopen(descriptor, "wb") as output_file:
            output_file.write(sanitized)
        return StoredBrandImage(
            digest=hashlib.sha256(sanitized).hexdigest(),
            byte_size=len(sanitized),
            width=stored_width,
            height=stored_height,
        )

    def path(self, reference: str) -> Path:
        self._validate_reference(reference)
        return self.root / reference

    def delete(self, reference: str) -> None:
        try:
            self.path(reference).unlink(missing_ok=True)
        except InvalidBrandImage:
            return

    def _read_bounded(self, source: BinaryIO) -> bytes:
        chunks: list[bytes] = []
        total = 0
        while chunk := source.read(min(64 * 1024, self.maximum_bytes + 1 - total)):
            total += len(chunk)
            if total > self.maximum_bytes:
                raise InvalidBrandImage("invalid brand image")
            chunks.append(chunk)
        if not chunks:
            raise InvalidBrandImage("invalid brand image")
        return b"".join(chunks)

    @staticmethod
    def _validate_reference(reference: str) -> None:
        if _REFERENCE.fullmatch(reference) is None or Path(reference).name != reference:
            raise InvalidBrandImage("invalid brand image")


def configured_brand_media_storage() -> LocalBrandMediaStorage:
    root = Path(
        os.environ.get(
            "VPN_SALE_BRAND_MEDIA_ROOT",
            "/var/lib/vpnsale/private/branding",
        )
    )
    return LocalBrandMediaStorage(root)
