"""Admin/debug command rendering tests for Ops Hub."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from ops_hub.bot.client import OpsHubBot
from ops_hub.bot.cogs.admin import AdminCog
from ops_hub.core.config import Settings
from ops_hub.core.container import build_container


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "discord_token": "token",
        "guild_id": 123456,
        "admin_user_ids": [],
        "admin_role_ids": [],
        "operator_user_ids": [],
        "operator_role_ids": [],
        "operator_bluefolder_user_map": {},
        "operator_mapping_file": None,
        "log_level": "INFO",
        "environment": "dev",
        "photo_ingest_channel_id": 222,
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


def _build_cog(**overrides: object) -> AdminCog:
    settings = _settings(**overrides)
    bot = OpsHubBot(settings=settings, container=build_container(settings))
    return AdminCog(bot)


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


def test_build_ops_status_reports_basic_runtime_state() -> None:
    cog = _build_cog()

    result = cog._build_ops_status()

    assert "Ops Hub Status" in result
    assert "Environment: `dev`" in result
    assert "Guild sync: guild" in result
    assert "Configured guild id: `123456`" in result
    assert "Photo ingest listener channel: `222`" in result
    assert "Bot identity: not connected" in result


def test_build_config_check_hides_secret_values() -> None:
    cog = _build_cog(
        bluefolder_api_key="secret-key",
        bluefolder_account_name="acme",
    )

    result = cog._build_config_check()

    assert "Discord token: set" in result
    assert "BlueFolder credentials: configured" in result
    assert "secret-key" not in result
    assert "BlueFolder library path: not set" in result


def test_build_service_status_reports_adapter_states() -> None:
    cog = _build_cog()

    result = asyncio.run(cog._build_service_status())

    assert "Ops Hub Service Status" in result
    assert "BlueFolder: `unconfigured`" in result
    assert "Dispatch: `unconfigured`" in result
    assert "Parts Cannon: `unconfigured`" in result
    assert "Photo ingest: `placeholder`" in result
    assert "Notifications: `dry_run` via `logger`" in result
    assert "Notification notices sent: `0`" in result


def test_build_recent_notices_renders_latest_entries() -> None:
    cog = _build_cog()
    asyncio.run(
        cog.bot.container.notification_service.send_notice(
            topic="parts.lookup",
            message="Parts lookup requested for SR-100.",
        )
    )

    result = asyncio.run(cog._build_recent_notices())

    assert "Recent Notices" in result
    assert "`parts.lookup` via `dry_run`" in result
    assert "Parts lookup requested for SR-100." in result


def test_build_operator_mappings_renders_current_map() -> None:
    cog = _build_cog(operator_bluefolder_user_map={42: 13051})

    result = cog._build_operator_mappings()

    assert "Operator Mappings" in result
    assert "Discord user `42` -> BlueFolder user `13051`" in result


def test_is_admin_allows_configured_user_id() -> None:
    cog = _build_cog(admin_user_ids=[42])

    result = cog._is_admin(_DummyInteraction(user=_DummyUser(id=42, roles=[])))

    assert result is True


def test_is_admin_allows_configured_role_id() -> None:
    cog = _build_cog(admin_role_ids=[7])

    result = cog._is_admin(_DummyInteraction(user=_DummyUser(id=42, roles=[_DummyRole(id=7)])))

    assert result is True


def test_is_admin_rejects_unconfigured_user() -> None:
    cog = _build_cog(admin_user_ids=[100], admin_role_ids=[200])

    result = cog._is_admin(_DummyInteraction(user=_DummyUser(id=42, roles=[_DummyRole(id=7)])))

    assert result is False
