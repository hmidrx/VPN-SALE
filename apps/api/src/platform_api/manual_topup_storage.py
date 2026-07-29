"""Private receipt storage; callers only persist the returned generated key."""

from __future__ import annotations

import hashlib
import io
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from PIL import Image, UnidentifiedImageError

MAX_RECEIPT_BYTES = 5 * 1024 * 1024
ALLOWED_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
_FORMATS = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "WEBP": ("image/webp", ".webp"),
}


class InvalidReceipt(ValueError):
    """A deliberately generic validation error safe for an API response."""


@dataclass(frozen=True)
class StoredReceipt:
    storage_key: str
    sanitized_sha256: str
    byte_size: int
    media_type: str
    width: int
    height: int


class LocalPrivateReceiptStorage:
    def __init__(
        self,
        root: Path,
        *,
        maximum_bytes: int = MAX_RECEIPT_BYTES,
        dimension_limit: int = 8_192,
        pixel_limit: int = 40_000_000,
    ) -> None:
        self.root = root.resolve()
        self.maximum_bytes = maximum_bytes
        self.dimension_limit = dimension_limit
        self.pixel_limit = pixel_limit
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)

    def store(self, source: BinaryIO, declared_media_type: str) -> StoredReceipt:
        if declared_media_type not in ALLOWED_MEDIA_TYPES:
            raise InvalidReceipt("invalid receipt")
        raw = self._read_bounded(source)
        try:
            with Image.open(io.BytesIO(raw)) as image:
                image.verify()
            with Image.open(io.BytesIO(raw)) as image:
                media_type, suffix = _FORMATS[image.format or ""]
                if media_type != declared_media_type or getattr(image, "n_frames", 1) != 1:
                    raise InvalidReceipt("invalid receipt")
                width, height = image.size
                if (
                    width <= 0
                    or height <= 0
                    or max(width, height) > self.dimension_limit
                    or width * height > self.pixel_limit
                ):
                    raise InvalidReceipt("invalid receipt")
                sanitized = self._sanitize(image, media_type)
        except (KeyError, OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
            raise InvalidReceipt("invalid receipt") from exc
        key = f"{secrets.token_hex(16)}{suffix}"
        destination = self.root / key
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        descriptor = os.open(destination, flags, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(sanitized)
        return StoredReceipt(
            key, hashlib.sha256(sanitized).hexdigest(), len(sanitized), media_type, width, height
        )

    def open(self, storage_key: str) -> BinaryIO:
        if Path(storage_key).name != storage_key:
            raise FileNotFoundError
        return (self.root / storage_key).open("rb")

    def delete(self, storage_key: str) -> None:
        if Path(storage_key).name == storage_key:
            (self.root / storage_key).unlink(missing_ok=True)

    def _read_bounded(self, source: BinaryIO) -> bytes:
        chunks: list[bytes] = []
        total = 0
        while chunk := source.read(min(64 * 1024, self.maximum_bytes + 1 - total)):
            total += len(chunk)
            if total > self.maximum_bytes:
                raise InvalidReceipt("invalid receipt")
            chunks.append(chunk)
        if not chunks:
            raise InvalidReceipt("invalid receipt")
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
