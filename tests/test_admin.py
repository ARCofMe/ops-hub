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
        notification_channel_id=777,
    )

    result = cog._build_config_check()

    assert "Discord token: set" in result
    assert "Notification channel: `777`" in result
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
    assert "Parts queue open: `0` of `0` total" in result
    assert "Parts queue synced: `0`" in result
    assert "Photo ingest: `placeholder`" in result
    assert "Photo features:" in result
    assert "`mdlsn_upload`: `enabled` via `env`" in result
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


def test_build_technician_mappings_renders_current_map() -> None:
    cog = _build_cog(technician_bluefolder_user_map={42: 13051})

    result = cog._build_technician_mappings()

    assert "Technician Mappings" in result
    assert "<@42> (BlueFolder `13051`)" in result


def test_build_command_access_describes_current_scopes() -> None:
    cog = _build_cog()

    result = cog._build_command_access()

    assert "`/ops_status`, `/config_check`, `/service_status`, `/recent_notices`, `/technician_mappings`, `/export_technician_mappings`, `/reload_technician_mappings`, `/set_technician_mapping`, `/remove_technician_mapping`, `/command_access`, `/photo_features`, `/set_photo_feature`, `/clear_photo_feature`: admin only" in result
    assert "`/job`, `/assignments`: technicians, dispatchers, admins" in result
    assert "`/eta`, `/enroute`, `/no_answer`, `/not_home`: technicians, admins" in result
    assert "`/mdlsn`, `/photo_archive`: technicians, admins (if enabled)" in result
    assert "`/photo_status`: technicians, parts, dispatchers, admins (if mailbox scan is enabled)" in result
    assert "`/photo_reminder_check`: dispatchers, admins" in result
    assert "`/part_request`, `/my_part_requests`, `/missing_part`, `/damaged_part`: technicians, parts, admins" in result
    assert "`/parts_brief`, `/parts_notes`: technicians, parts, dispatchers, admins" in result
    assert "`/tech_assignments`, `/tech_job`, `/dispatch_board`, `/dispatch_attention`, `/dispatch_next`, `/photo_compliance_board`: dispatchers, admins" in result
    assert "`/part`, `/part_requests`, `/part_request_detail`, `/part_update`, `/part_claim`, `/part_unclaim`, `/part_sync`, `/part_reconcile`, `/part_ordered`, `/part_eta`, `/part_tracking`, `/part_received`, `/part_ready`: parts, admins" in result


def test_build_photo_features_reports_default_states() -> None:
    cog = _build_cog()

    result = cog._build_photo_features()

    assert "Photo Features" in result
    assert "`mdlsn_upload`: `enabled` via `env`" in result
    assert "`photo_mailbox_scan`: `disabled` via `env`" in result


def test_set_photo_feature_persists_override() -> None:
    cog = _build_cog()

    result = cog._build_set_photo_feature("mdlsn_upload", False)

    assert result == "Photo feature `mdlsn_upload` is now `disabled`."
    assert cog.bot.container.photo_feature_flags_service.is_enabled("mdlsn_upload") is False


def test_clear_photo_feature_clears_override() -> None:
    cog = _build_cog()
    cog.bot.container.photo_feature_flags_service.set_override("mdlsn_upload", False)

    result = cog._build_clear_photo_feature("mdlsn_upload")

    assert result == "Cleared photo feature override for `mdlsn_upload`."
    assert cog.bot.container.photo_feature_flags_service.is_enabled("mdlsn_upload") is True


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
