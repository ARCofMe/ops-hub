"""Photo ingest listener tests for Ops Hub."""

import asyncio

from ops_hub.core.config import Settings
from ops_hub.integrations.photo_ingest_adapter import PhotoIngestAdapter
from ops_hub.models.requests import PhotoIngestMessage
from ops_hub.services.photo_ingest import PhotoIngestService


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "discord_token": "token",
        "guild_id": None,
        "log_level": "INFO",
        "environment": "dev",
        "photo_ingest_channel_id": 123,
        "bluefolder_api_path": None,
        "bluebot_discord_extension_path": None,
        "photo_ingest_project_path": None,
        "parts_cannon_project_path": None,
        "dispatch_project_path": None,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_photo_ingest_service_ignores_unconfigured_channel() -> None:
    service = PhotoIngestService(
        settings=_settings(photo_ingest_channel_id=None),
        adapter=PhotoIngestAdapter(base_path=None),
    )

    result = asyncio.run(
        service.handle_message(
            PhotoIngestMessage(
                channel_id=123,
                message_id=1,
                author_id=42,
                content="hello",
                attachment_count=1,
            )
        )
    )

    assert result.handled is False
    assert result.status == "ignored_channel"


def test_photo_ingest_service_ignores_other_channels() -> None:
    service = PhotoIngestService(
        settings=_settings(photo_ingest_channel_id=999),
        adapter=PhotoIngestAdapter(base_path=None),
    )

    result = asyncio.run(
        service.handle_message(
            PhotoIngestMessage(
                channel_id=123,
                message_id=1,
                author_id=42,
                content="hello",
                attachment_count=1,
            )
        )
    )

    assert result.handled is False
    assert result.status == "ignored_channel"


def test_photo_ingest_service_handles_attachment_messages_in_configured_channel() -> None:
    service = PhotoIngestService(
        settings=_settings(photo_ingest_channel_id=123),
        adapter=PhotoIngestAdapter(base_path=None),
    )

    result = asyncio.run(
        service.handle_message(
            PhotoIngestMessage(
                channel_id=123,
                message_id=1,
                author_id=42,
                content="see attached",
                attachment_count=2,
            )
        )
    )

    assert result.handled is True
    assert result.status == "placeholder_ready"
