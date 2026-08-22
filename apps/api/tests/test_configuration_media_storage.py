from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from platform_api.configuration_media_storage import (
    InvalidBrandImage,
    LocalBrandMediaStorage,
)


def png_bytes(size: tuple[int, int] = (96, 72)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, (85, 108, 220)).save(output, format="PNG")
    return output.getvalue()


def test_brand_logo_is_sanitized_to_opaque_webp(tmp_path: Path) -> None:
    storage = LocalBrandMediaStorage(tmp_path)
    reference = "BRAND-" + "a" * 24

    result = storage.store(reference, io.BytesIO(png_bytes()), "image/png")

    assert result.media_type == "image/webp"
    assert result.width == 96
    assert result.height == 72
    assert result.byte_size > 0
    assert len(result.digest) == 64
    with Image.open(storage.path(reference)) as stored:
        assert stored.format == "WEBP"
        assert stored.size == (96, 72)


@pytest.mark.parametrize(
    ("reference", "payload", "media_type"),
    [
        ("../brand", png_bytes(), "image/png"),
        ("BRAND-" + "b" * 24, b"not-an-image", "image/png"),
        ("BRAND-" + "c" * 24, png_bytes(), "image/svg+xml"),
    ],
)
def test_brand_logo_rejects_unsafe_input(
    tmp_path: Path,
    reference: str,
    payload: bytes,
    media_type: str,
) -> None:
    storage = LocalBrandMediaStorage(tmp_path)
    with pytest.raises(InvalidBrandImage):
        storage.store(reference, io.BytesIO(payload), media_type)


def test_brand_logo_rejects_oversized_upload(tmp_path: Path) -> None:
    storage = LocalBrandMediaStorage(tmp_path, maximum_bytes=32)
    with pytest.raises(InvalidBrandImage):
        storage.store("BRAND-" + "d" * 24, io.BytesIO(png_bytes()), "image/png")
