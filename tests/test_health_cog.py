"""Health/help command rendering tests for Ops Hub."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from ops_hub.bot.client import OpsHubBot
from ops_hub.bot.cogs.health import HealthCog
from ops_hub.core.config import Settings
from ops_hub.core.container import build_container


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
        "parts_request_file": None,
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


@dataclass(slots=True)
class _DummyUser:
    id: int
    roles: list[object] | None = None


@dataclass(slots=True)
class _DummyInteraction:
    user: _DummyUser
    response: object | None = None

    def __post_init__(self) -> None:
        self.response = _DummyResponse()


class _DummyResponse:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    async def send_message(self, content: str, *, ephemeral: bool, embed=None) -> None:
        self.messages.append({"content": content, "ephemeral": ephemeral, "embed": embed})


@dataclass(slots=True)
class _DummyRole:
    id: int


def test_build_help_text_lists_only_open_commands_for_unprivileged_user() -> None:
    settings = _settings()
    bot = OpsHubBot(settings=settings, container=build_container(settings))
    cog = HealthCog(bot)
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))

    result = cog._build_help_text(interaction)

    assert "**Ops Hub Command Guide**" in result
    assert "**Open**" in result
    assert "`/ping`, `/help`" in result
    assert "**Technician**" not in result
    assert "**Dispatch**" not in result
    assert "**Parts**" not in result
    assert "**Admin**" not in result
    assert "No role-specific commands are currently available" in result


def test_build_help_text_lists_technician_surface_for_technician_user() -> None:
    settings = _settings(technician_user_ids=[42])
    bot = OpsHubBot(settings=settings, container=build_container(settings))
    cog = HealthCog(bot)
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))

    result = cog._build_help_text(interaction)

    assert "**Technician**" in result
    assert "/missing_part" in result
    assert "/customer" in result
    assert "/eta" in result
    assert "/enroute" in result
    assert "/start" in result
    assert "/no_answer" in result
    assert "/not_home" in result
    assert "/note" in result
    assert "/reschedule_needed" in result
    assert "**Dispatch**" not in result
    assert "**Parts**" not in result
    assert "**Admin**" not in result


def test_build_help_text_lists_dispatch_surface_for_dispatcher_user() -> None:
    settings = _settings(dispatcher_user_ids=[42])
    bot = OpsHubBot(settings=settings, container=build_container(settings))
    cog = HealthCog(bot)
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))

    result = cog._build_help_text(interaction)

    assert "**Dispatch**" in result
    assert "/dispatch_attention" in result
    assert "/dispatch_next" in result
    assert "/photo_compliance_board" in result
    assert "/attention_ack" in result
    assert "/attention_history" in result
    assert "**Parts**" not in result
    assert "**Admin**" not in result


def test_build_help_text_lists_parts_and_admin_surfaces_for_admin_user() -> None:
    settings = _settings(admin_user_ids=[42])
    bot = OpsHubBot(settings=settings, container=build_container(settings))
    cog = HealthCog(bot)
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))

    result = cog._build_help_text(interaction)

    assert "**Technician**" in result
    assert "**Dispatch**" in result
    assert "**Parts**" in result
    assert "**Admin**" in result
    assert "/part_reconcile" in result
    assert "/part_tracking" in result
    assert "/technician_mappings" in result
    assert "/policy_run_now" in result


def test_ping_command_sends_ephemeral_pong() -> None:
    settings = _settings()
    bot = OpsHubBot(settings=settings, container=build_container(settings))
    cog = HealthCog(bot)
    interaction = _DummyInteraction(user=_DummyUser(id=42))

    asyncio.run(cog.ping.callback(cog, interaction))

    assert interaction.response.messages == [{"content": "pong", "ephemeral": True, "embed": None}]


def test_help_command_sends_ephemeral_help_text() -> None:
    settings = _settings()
    bot = OpsHubBot(settings=settings, container=build_container(settings))
    cog = HealthCog(bot)
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))

    asyncio.run(cog.help.callback(cog, interaction))

    assert interaction.response.messages[0]["ephemeral"] is True
    assert "**Ops Hub Command Guide**" in str(interaction.response.messages[0]["content"])
    assert "No role-specific commands are currently available" in str(interaction.response.messages[0]["content"])
