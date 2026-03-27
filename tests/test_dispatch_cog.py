"""Dispatcher command access tests for Ops Hub."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import patch

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
class _DummyGuild:
    members: list[_DummyUser]


class _FetchGuild:
    def __init__(self, members: list[_DummyUser]) -> None:
        self.members: list[_DummyUser] = []
        self._fetched_members = members

    async def fetch_members(self, *, limit=None):
        for member in self._fetched_members:
            yield member


@dataclass(slots=True)
class _DummyInteraction:
    user: _DummyUser
    guild: _DummyGuild | None = None
    response: object | None = None
    followup: object | None = None

    def __post_init__(self) -> None:
        self.response = _DummyResponse()
        self.followup = _DummyFollowup()


class _DummyResponse:
    def __init__(self) -> None:
        self.deferred = False
        self.messages: list[dict[str, object]] = []

    async def send_message(self, content: str, *, ephemeral: bool, embed=None) -> None:
        self.messages.append({"content": content, "ephemeral": ephemeral, "embed": embed})

    async def defer(self, *, ephemeral: bool) -> None:
        self.deferred = ephemeral


class _DummyFollowup:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    async def send(self, content: str, *, ephemeral: bool, embed=None) -> None:
        self.messages.append({"content": content, "ephemeral": ephemeral, "embed": embed})


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


def test_dispatch_cog_board_uses_only_current_technician_members() -> None:
    cog = _build_cog(
        dispatcher_user_ids=[99],
        technician_role_ids=[7],
        technician_bluefolder_user_map={42: 13051, 50: 13051, 99: 99999},
    )
    interaction = _DummyInteraction(
        user=_DummyUser(id=99, roles=[]),
        guild=_DummyGuild(
            members=[
                _DummyUser(id=42, roles=[_DummyRole(id=7)]),
                _DummyUser(id=50, roles=[]),
                _DummyUser(id=99, roles=[]),
            ]
        ),
    )

    records = asyncio.run(cog._technician_dispatch_mappings(interaction))

    assert len(records) == 1
    assert records[0].discord_user_id == 42
    assert records[0].bluefolder_user_id == 13051


def test_dispatch_cog_uses_all_mapping_records_without_guild_context() -> None:
    cog = _build_cog(technician_bluefolder_user_map={42: 13051, 50: 13052})
    interaction = _DummyInteraction(user=_DummyUser(id=99, roles=[]), guild=None)

    records = asyncio.run(cog._technician_dispatch_mappings(interaction))

    assert [(record.discord_user_id, record.bluefolder_user_id) for record in records] == [
        (42, 13051),
        (50, 13052),
    ]


def test_dispatch_cog_fetches_members_when_guild_cache_is_empty() -> None:
    cog = _build_cog(
        dispatcher_user_ids=[99],
        technician_role_ids=[7],
        technician_bluefolder_user_map={42: 13051, 50: 13052},
    )
    interaction = _DummyInteraction(
        user=_DummyUser(id=99, roles=[]),
        guild=_FetchGuild(
            [
                _DummyUser(id=42, roles=[_DummyRole(id=7)]),
                _DummyUser(id=50, roles=[]),
            ]
        ),
    )

    records = asyncio.run(cog._technician_dispatch_mappings(interaction))

    assert len(records) == 1
    assert records[0].discord_user_id == 42
    assert records[0].bluefolder_user_id == 13051


def test_dispatch_cog_tech_assignments_sends_result() -> None:
    cog = _build_cog(dispatcher_user_ids=[99])
    interaction = _DummyInteraction(user=_DummyUser(id=99, roles=[]))

    async def fake_lookup(self, request):
        assert request.target_bluefolder_user_id == 13051
        assert request.requested_by_user_id == 99
        return SimpleNamespace(message="Assignments ready")

    with patch.object(type(cog.bot.container.dispatch_service), "lookup_assignments", new=fake_lookup):
        asyncio.run(cog.tech_assignments.callback(cog, interaction, bluefolder_user_id=13051))

    assert interaction.response.messages == [{"content": "Assignments ready", "ephemeral": True, "embed": None}]


def test_dispatch_cog_dispatch_attention_uses_deferred_followup() -> None:
    cog = _build_cog(dispatcher_user_ids=[99])
    interaction = _DummyInteraction(user=_DummyUser(id=99, roles=[]), guild=None)

    async def fake_lookup(self, mappings, *, stage_filter=None, technician_bluefolder_user_id=None):
        assert mappings == []
        assert stage_filter == "part_ready"
        assert technician_bluefolder_user_id == 13051
        return SimpleNamespace(message="Attention board")

    with patch.object(type(cog.bot.container.dispatch_service), "lookup_dispatch_attention", new=fake_lookup):
        asyncio.run(
            cog.dispatch_attention.callback(
                cog,
                interaction,
                stage="part_ready",
                bluefolder_user_id=13051,
            )
        )

    assert interaction.response.deferred is True
    assert interaction.followup.messages == [{"content": "Attention board", "ephemeral": True, "embed": None}]


def test_dispatch_cog_dispatch_heatmap_sends_embed() -> None:
    cog = _build_cog(dispatcher_user_ids=[99])
    interaction = _DummyInteraction(user=_DummyUser(id=99, roles=[]), guild=None)

    async def fake_lookup(self, mappings, *, technician_bluefolder_user_id=None):
        assert mappings == []
        assert technician_bluefolder_user_id == 13051
        return SimpleNamespace(message="Heatmap ready", image_url="https://example.com/heatmap.png")

    with patch.object(type(cog.bot.container.dispatch_service), "lookup_assignment_heatmap", new=fake_lookup):
        asyncio.run(cog.dispatch_heatmap.callback(cog, interaction, bluefolder_user_id=13051))

    assert interaction.response.deferred is True
    assert interaction.followup.messages[0]["content"] == "Heatmap ready"
    assert interaction.followup.messages[0]["ephemeral"] is True
    embed = interaction.followup.messages[0]["embed"]
    assert embed is not None
    assert embed.image.url == "https://example.com/heatmap.png"
