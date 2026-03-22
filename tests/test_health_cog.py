"""Health/help command rendering tests for Ops Hub."""

from __future__ import annotations

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


def test_build_help_text_lists_current_role_surfaces() -> None:
    settings = _settings()
    bot = OpsHubBot(settings=settings, container=build_container(settings))
    cog = HealthCog(bot)

    result = cog._build_help_text()

    assert "Ops Hub Command Guide" in result
    assert "Open access: `/ping`, `/ops_help`" in result
    assert "/missing_part" in result
    assert "Dispatch: `/job`, `/assignments`, `/tech_assignments`, `/tech_job`, `/dispatch_board`, `/dispatch_attention`, `/parts_brief`, `/parts_notes`" in result
    assert "/part_reconcile" in result
    assert "/part_tracking" in result
    assert "/technician_mappings" in result
