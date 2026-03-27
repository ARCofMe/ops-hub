"""Discord bot startup and error-handling tests for Ops Hub."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

import discord

from ops_hub.bot.client import OpsHubBot
from ops_hub.core.config import Settings
from ops_hub.core.container import build_container
from ops_hub.models.requests import PhotoAttachmentPayload, PhotoIngestResult
from ops_hub.services.photo_ingest import PhotoIngestService


@dataclass(slots=True)
class _DummyCommand:
    name: str


class _DummyResponse:
    def __init__(self, done: bool) -> None:
        self._done = done
        self.messages: list[tuple[str, bool]] = []

    def is_done(self) -> bool:
        return self._done

    async def send_message(self, message: str, *, ephemeral: bool) -> None:
        self.messages.append((message, ephemeral))


class _DummyFollowup:
    def __init__(self) -> None:
        self.messages: list[tuple[str, bool]] = []

    async def send(self, message: str, *, ephemeral: bool) -> None:
        self.messages.append((message, ephemeral))


class _DummyUser:
    id = 123
    bot = False
    display_name = "Mike Smith"
    global_name = "Mike Smith"
    name = "mike.smith"


class _DummyAttachment:
    def __init__(self, filename: str, content_type: str, data: bytes) -> None:
        self.filename = filename
        self.content_type = content_type
        self._data = data

    async def read(self) -> bytes:
        return self._data


class _DummyChannel:
    id = 321


class _DummyMessage:
    def __init__(self, *, content: str, attachments: list[_DummyAttachment] | None = None) -> None:
        self.author = _DummyUser()
        self.channel = _DummyChannel()
        self.id = 555
        self.content = content
        self.attachments = attachments or []


class _DummyInteraction:
    def __init__(self, *, done: bool) -> None:
        self.command = _DummyCommand(name="job")
        self.user = _DummyUser()
        self.guild_id = 456
        self.channel_id = 789
        self.response = _DummyResponse(done=done)
        self.followup = _DummyFollowup()


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "discord_token": "token",
        "guild_id": None,
        "admin_user_ids": [],
        "admin_role_ids": [],
        "technician_user_ids": [],
        "technician_role_ids": [],
        "parts_user_ids": [],
        "parts_role_ids": [],
        "dispatcher_user_ids": [],
        "dispatcher_role_ids": [],
        "technician_bluefolder_user_map": {},
        "technician_mapping_file": None,
        "log_level": "INFO",
        "environment": "dev",
        "photo_ingest_channel_id": None,
        "bluefolder_api_path": None,
        "bluefolder_api_key": None,
        "bluefolder_account_name": None,
        "bluefolder_base_url": None,
        "bluebot_discord_extension_path": None,
        "photo_ingest_project_path": None,
        "parts_cannon_project_path": None,
        "dispatch_project_path": None,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _build_bot(**overrides: object) -> OpsHubBot:
    settings = _settings(**overrides)
    return OpsHubBot(settings=settings, container=build_container(settings))


def test_on_app_command_error_uses_initial_response_before_send() -> None:
    bot = _build_bot()
    interaction = _DummyInteraction(done=False)

    asyncio.run(bot.on_app_command_error(interaction, discord.app_commands.AppCommandError("boom")))

    assert interaction.response.messages == [("Ops Hub hit an unexpected error.", True)]
    assert interaction.followup.messages == []


def test_on_app_command_error_uses_followup_after_response() -> None:
    bot = _build_bot()
    interaction = _DummyInteraction(done=True)

    asyncio.run(bot.on_app_command_error(interaction, discord.app_commands.AppCommandError("boom")))

    assert interaction.response.messages == []
    assert interaction.followup.messages == [("Ops Hub hit an unexpected error.", True)]


def test_setup_hook_reraises_sync_failure() -> None:
    bot = _build_bot()

    async def fake_load_extension(extension: str) -> None:
        return None

    async def fake_sync(*, guild: discord.Object | None = None) -> list[object]:
        raise RuntimeError("sync failed")

    bot.load_extension = fake_load_extension  # type: ignore[method-assign]
    bot.tree.sync = fake_sync  # type: ignore[method-assign]

    try:
        asyncio.run(bot.setup_hook())
    except RuntimeError as exc:
        assert str(exc) == "sync failed"
    else:
        raise AssertionError("setup_hook() should re-raise sync failures")


def test_on_message_builds_photo_payloads_for_image_attachments() -> None:
    bot = _build_bot(photo_ingest_channel_id=321)
    captured: dict[str, Any] = {}

    async def fake_handle_message(self, message) -> PhotoIngestResult:
        captured["message"] = message
        return PhotoIngestResult(handled=False, status="missing_sr_reference", message="missing")

    async def fake_process_commands(message) -> None:
        captured["processed"] = message.id

    bot.process_commands = fake_process_commands  # type: ignore[method-assign]
    with patch.object(PhotoIngestService, "handle_message", new=fake_handle_message):
        asyncio.run(
            bot.on_message(
                _DummyMessage(
                    content="SR-12345",
                    attachments=[
                        _DummyAttachment("one.png", "image/png", b"img1"),
                        _DummyAttachment("note.txt", "text/plain", b"text"),
                    ],
                )
            )
        )

    message = captured["message"]
    assert message.channel_id == 321
    assert message.author_label == "Mike Smith"
    assert message.attachment_count == 2
    assert len(message.attachments) == 1
    assert isinstance(message.attachments[0], PhotoAttachmentPayload)
    assert message.attachments[0].filename == "one.png"
    assert captured["processed"] == 555


def test_on_message_skips_attachment_reads_for_other_channels() -> None:
    bot = _build_bot(photo_ingest_channel_id=999)
    captured: dict[str, Any] = {}

    async def fake_handle_message(self, message) -> PhotoIngestResult:
        captured["message"] = message
        return PhotoIngestResult(handled=False, status="ignored_channel", message="ignored")

    async def fake_process_commands(message) -> None:
        captured["processed"] = message.id

    bot.process_commands = fake_process_commands  # type: ignore[method-assign]
    with patch.object(PhotoIngestService, "handle_message", new=fake_handle_message):
        asyncio.run(
            bot.on_message(
                _DummyMessage(
                    content="SR-12345",
                    attachments=[_DummyAttachment("one.png", "image/png", b"img1")],
                )
            )
        )

    message = captured["message"]
    assert message.channel_id == 321
    assert message.attachments == []
    assert captured["processed"] == 555
