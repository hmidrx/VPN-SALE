import pytest

from telegram_bot.transport.polling import UrlLibTelegramTransport, _receipt_from_update


def _message(payload: dict[str, object]) -> dict[str, object]:
    return {
        "update_id": 9,
        "message": {"chat": {"id": 1, "type": "private"}, "from": {"id": 42}, **payload},
    }


def test_selects_highest_suitable_photo_without_exposing_metadata() -> None:
    receipt = _receipt_from_update(
        _message(
            {
                "photo": [
                    {"file_id": "small", "file_size": 100},
                    {"file_id": "large", "file_size": 500},
                    {"file_id": "too-large", "file_size": 5 * 1024 * 1024 + 1},
                ]
            }
        )
    )
    assert receipt is not None
    assert receipt[1:] == ("large", "image/jpeg", 500)


@pytest.mark.parametrize("mime", ["image/jpeg", "image/png", "image/webp"])
def test_accepts_supported_image_documents(mime: str) -> None:
    receipt = _receipt_from_update(
        _message(
            {
                "document": {
                    "file_id": "document",
                    "mime_type": mime,
                    "file_size": 1024,
                }
            }
        )
    )
    assert receipt is not None and receipt[2] == mime


def test_rejects_non_image_document() -> None:
    assert (
        _receipt_from_update(
            _message(
                {
                    "document": {
                        "file_id": "document",
                        "mime_type": "application/pdf",
                        "file_size": 1024,
                    }
                }
            )
        )
        is None
    )


@pytest.mark.asyncio
async def test_download_rejects_user_supplied_url_before_network() -> None:
    transport = UrlLibTelegramTransport("not-a-real-token")
    with pytest.raises(RuntimeError, match="download failed"):
        await transport.download_file("https://evil.example/receipt.png", 5 * 1024 * 1024)
