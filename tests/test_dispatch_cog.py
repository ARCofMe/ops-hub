"""Dispatcher command access tests for Ops Hub."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from discord import app_commands

from ops_hub.bot.client import OpsHubBot
from ops_hub.bot.cogs.dispatch import DispatchCog
from ops_hub.core.config import Settings
from ops_hub.core.container import build_container


@dataclass(slots=True)
class _DummyRole:
    id: int


@dataclass(slots=True)
class _DummyUser:
    id: int
    roles: list[_DummyRole]


@dataclass(slots=True)
class _DummyInteraction:
    user: _DummyUser


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


def _build_cog(**overrides: object) -> DispatchCog:
    settings = _settings(**overrides)
    bot = OpsHubBot(settings=settings, container=build_container(settings))
    return DispatchCog(bot)


def test_dispatch_cog_allows_dispatcher_user() -> None:
    cog = _build_cog(dispatcher_user_ids=[42])
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))

    assert asyncio.run(cog.cog_app_command_check(interaction)) is True


def test_dispatch_cog_allows_admin_user() -> None:
    cog = _build_cog(admin_user_ids=[99])
    interaction = _DummyInteraction(user=_DummyUser(id=99, roles=[]))

    assert asyncio.run(cog.cog_app_command_check(interaction)) is True


def test_dispatch_cog_rejects_non_dispatch_user() -> None:
    cog = _build_cog(dispatcher_user_ids=[42], admin_user_ids=[99])
    interaction = _DummyInteraction(user=_DummyUser(id=7, roles=[]))

    try:
        asyncio.run(cog.cog_app_command_check(interaction))
    except app_commands.CheckFailure as exc:
        assert str(exc) == "You do not have permission to use this command."
    else:
        raise AssertionError("Expected dispatch command check to reject unconfigured user")


def test_dispatch_cog_board_uses_mapping_records() -> None:
    cog = _build_cog(dispatcher_user_ids=[42], technician_bluefolder_user_map={42: 13051})

    records = cog.bot.container.technician_directory_service.mapping_records()

    assert len(records) == 1
    assert records[0].discord_user_id == 42
    assert records[0].bluefolder_user_id == 13051
