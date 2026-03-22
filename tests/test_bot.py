"""Discord bot startup and error-handling tests for Ops Hub."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import discord

from ops_hub.bot.client import OpsHubBot
from ops_hub.core.config import Settings
from ops_hub.core.container import build_container


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
        "operator_user_ids": [],
        "operator_role_ids": [],
        "parts_user_ids": [],
        "parts_role_ids": [],
        "dispatcher_user_ids": [],
        "dispatcher_role_ids": [],
        "operator_bluefolder_user_map": {},
        "operator_mapping_file": None,
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
