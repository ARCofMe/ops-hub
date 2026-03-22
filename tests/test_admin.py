"""Admin/debug command rendering tests for Ops Hub."""

from __future__ import annotations

import asyncio

from ops_hub.bot.client import OpsHubBot
from ops_hub.bot.cogs.admin import AdminCog
from ops_hub.core.config import Settings
from ops_hub.core.container import build_container


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "discord_token": "token",
        "guild_id": 123456,
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
    assert "Parts Cannon: `unconfigured`" in result
    assert "Photo ingest: `placeholder`" in result
    assert "Notifications: `placeholder_ready`" in result
