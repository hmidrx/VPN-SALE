import io
from pathlib import Path

import pytest
from PIL import Image

from platform_api.manual_topup_storage import InvalidReceipt, LocalPrivateReceiptStorage


def _image() -> io.BytesIO:
    output = io.BytesIO()
    image = Image.new("RGB", (10, 10), "white")
    image.save(output, format="JPEG", exif=b"Exif\x00\x00test metadata")
    output.seek(0)
    return output


def test_receipt_is_reencoded_under_generated_private_name(tmp_path: Path) -> None:
    storage = LocalPrivateReceiptStorage(tmp_path)
    stored = storage.store(_image(), "image/jpeg")
    assert stored.storage_key.endswith(".jpg")
    assert "/" not in stored.storage_key
    assert len(stored.sanitized_sha256) == 64
    with storage.open(stored.storage_key) as content:
        with Image.open(content) as image:
            assert image.getexif() == {}
    assert (tmp_path.stat().st_mode & 0o777) == 0o700
    assert ((tmp_path / stored.storage_key).stat().st_mode & 0o777) == 0o600


def test_receipt_rejects_oversized_and_malformed_content(tmp_path: Path) -> None:
    storage = LocalPrivateReceiptStorage(tmp_path, maximum_bytes=10)
    with pytest.raises(InvalidReceipt):
        storage.store(io.BytesIO(b"x" * 11), "image/jpeg")
    with pytest.raises(InvalidReceipt):
        LocalPrivateReceiptStorage(tmp_path).store(io.BytesIO(b"not an image"), "image/png")
