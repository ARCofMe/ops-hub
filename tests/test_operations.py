"""Operations access and mapping tests for Ops Hub."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from discord import app_commands

from ops_hub.bot.client import OpsHubBot
from ops_hub.bot.cogs.operations import OperationsCog
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


def _build_cog(**overrides: object) -> OperationsCog:
    settings = _settings(**overrides)
    bot = OpsHubBot(settings=settings, container=build_container(settings))
    return OperationsCog(bot)


def test_operations_check_allows_configured_technician_user() -> None:
    cog = _build_cog(technician_user_ids=[42])
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))

    assert asyncio.run(cog.cog_app_command_check(interaction)) is True


def test_operations_check_allows_admin_user() -> None:
    cog = _build_cog(admin_user_ids=[99])
    interaction = _DummyInteraction(user=_DummyUser(id=99, roles=[]))

    assert asyncio.run(cog.cog_app_command_check(interaction)) is True


def test_operations_check_rejects_unconfigured_user() -> None:
    cog = _build_cog(technician_user_ids=[42], admin_user_ids=[99])
    interaction = _DummyInteraction(user=_DummyUser(id=7, roles=[]))

    try:
        asyncio.run(cog.cog_app_command_check(interaction))
    except app_commands.CheckFailure as exc:
        assert str(exc) == "You do not have permission to use this command."
    else:
        raise AssertionError("Expected operations command check to reject unconfigured user")


def test_resolve_identity_includes_bluefolder_mapping() -> None:
    cog = _build_cog(technician_user_ids=[42], technician_bluefolder_user_map={42: 13051})
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))

    identity = cog._resolve_identity(interaction)

    assert identity.is_technician is True
    assert identity.is_admin is False
    assert identity.bluefolder_user_id == 13051


def test_resolve_identity_includes_dispatcher_access() -> None:
    cog = _build_cog(dispatcher_user_ids=[42])
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))

    identity = cog._resolve_identity(interaction)

    assert identity.is_dispatcher is True
    assert identity.is_technician is False


def test_resolve_identity_includes_parts_access() -> None:
    cog = _build_cog(parts_user_ids=[42])
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))

    identity = cog._resolve_identity(interaction)

    assert identity.is_parts is True
    assert identity.is_technician is False


def test_operations_check_allows_dispatcher_user() -> None:
    cog = _build_cog(dispatcher_user_ids=[42])
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))

    assert asyncio.run(cog.cog_app_command_check(interaction)) is True


def test_parts_commands_allow_parts_user() -> None:
    cog = _build_cog(parts_user_ids=[42])
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))

    identity = cog._resolve_identity(interaction)

    assert cog._can_use_parts_queue(identity) is True
    assert cog._can_submit_parts_request(identity) is True
    assert cog._can_use_job_commands(identity) is False


def test_technician_can_submit_parts_request_but_not_manage_queue() -> None:
    cog = _build_cog(technician_user_ids=[42])
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))

    identity = cog._resolve_identity(interaction)

    assert cog._can_submit_parts_request(identity) is True
    assert cog._can_use_parts_queue(identity) is False


def test_technician_can_write_bluefolder_parts_issue() -> None:
    cog = _build_cog(technician_user_ids=[42])
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))

    identity = cog._resolve_identity(interaction)

    assert cog._can_write_parts_issue(identity) is True
    assert cog._can_view_parts_context(identity) is True
    assert cog._can_write_parts_update(identity) is False
    assert cog._can_upload_sr_photo(identity) is True


def test_technician_can_use_route_status_commands() -> None:
    cog = _build_cog(technician_user_ids=[42])
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))

    identity = cog._resolve_identity(interaction)

    assert cog._can_upload_sr_photo(identity) is True
    assert cog._can_log_field_event(identity) is True


def test_parts_can_write_bluefolder_parts_update() -> None:
    cog = _build_cog(parts_user_ids=[42])
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))

    identity = cog._resolve_identity(interaction)

    assert cog._can_write_parts_update(identity) is True
    assert cog._can_upload_sr_photo(identity) is False
