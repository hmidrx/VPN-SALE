from __future__ import annotations

import io
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from PIL import Image

from platform_api.support_attachment_storage import LocalPrivateSupportAttachmentStorage
from platform_worker.support_reply_delivery import (
    AgentAttachmentPayload,
    InvalidSupportNotification,
    SupportReplyDeliveryWorker,
)


def _png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (10, 10), (20, 40, 60)).save(output, format="PNG")
    return output.getvalue()


def test_worker_reads_only_hash_verified_sanitized_attachment() -> None:
    with TemporaryDirectory() as root:
        storage = LocalPrivateSupportAttachmentStorage(Path(root))
        reference = "SAT-0123456789abcdef01234567"
        stored = storage.store(reference, io.BytesIO(_png()), "image/png")
        payload = AgentAttachmentPayload(
            asset_reference=reference,
            filename="support-image.png",
            content_type=stored.media_type,
            byte_size=stored.byte_size,
            sha256=stored.sanitized_sha256,
        )
        worker = object.__new__(SupportReplyDeliveryWorker)
        worker.storage = storage
        verified = worker._read_attachment(payload)
        assert len(verified) == stored.byte_size

        with storage.open(reference) as source:
            original = source.read()
        Path(root, reference).write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
        with pytest.raises(InvalidSupportNotification):
            worker._read_attachment(payload)
