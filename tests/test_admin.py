"""Admin/debug command rendering tests for Ops Hub."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from unittest.mock import patch

from ops_hub.bot.client import OpsHubBot
from ops_hub.services.bluefolder import BlueFolderService
from ops_hub.bot.cogs.admin import AdminCog, _build_tech_map_suggestion, _parse_mapping_import_text
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
    name: str = "mike.smith"
    display_name: str = "Mike Smith"
    global_name: str | None = "Mike Smith"


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

    assert "`/ops_status`" in result
    assert "`/bluefolder_techs`" in result
    assert "`/export_member_map`" in result
    assert "`/suggest_tech_map`" in result
    assert "`/lookup_member`" in result
    assert "`/technician_mappings`" in result
    assert "`/export_technician_mappings`" in result
    assert "`/import_technician_mappings`" in result
    assert "`/reload_technician_mappings`" in result
    assert "`/job`, `/assignments`, `/customer`: technicians, dispatchers, admins" in result
    assert "`/eta`, `/enroute`, `/start`, `/no_answer`, `/not_home`, `/reschedule_needed`, `/note`: technicians, admins" in result
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


def test_build_tech_map_suggestion_matches_exact_names() -> None:
    result = _build_tech_map_suggestion(
        [
            {
                "discord_user_id": "42",
                "username": "mike.smith",
                "display_name": "Mike Smith",
                "global_name": None,
                "role_names": ["Technician"],
            }
        ],
        [
            {"id": 13051, "name": "Mike Smith", "email": "mike@example.com"},
            {"id": 13052, "name": "John Doe", "email": "john@example.com"},
        ],
    )

    assert result["suggested_discord_tech_map"] == {"42": 13051}
    assert "OPS_HUB_TECHNICIAN_BLUEFOLDER_USER_MAP=" in str(result["suggested_discord_tech_map_env"])


def test_build_bluefolder_techs_renders_export_and_ids(tmp_path) -> None:
    cog = _build_cog(member_export_path=str(tmp_path / "members.json"))

    async def fake_directory(self) -> dict[int, str]:
        return {13051: "Mike Smith", 14001: "John Doe"}

    with patch.object(BlueFolderService, "get_active_user_directory", new=fake_directory):
        result = asyncio.run(cog._build_bluefolder_techs())

    assert "BlueFolder Technicians (`2`)" in result
    assert "`13051` Mike Smith" in result
    assert any(path.name.startswith("members_bluefolder_techs") for path in tmp_path.iterdir())


def test_parse_mapping_import_text_accepts_env_line() -> None:
    result = _parse_mapping_import_text('OPS_HUB_TECHNICIAN_BLUEFOLDER_USER_MAP={"42":13051}')

    assert result == {42: 13051}


def test_parse_mapping_import_text_accepts_suggestion_export_payload() -> None:
    result = _parse_mapping_import_text(
        '{"suggested_discord_tech_map":{"42":13051,"84":14001},"matched":[]}'
    )

    assert result == {42: 13051, 84: 14001}


def test_build_lookup_member_reports_mapping_and_exact_match() -> None:
    cog = _build_cog(technician_bluefolder_user_map={42: 13051})

    async def fake_directory(self) -> dict[int, str]:
        return {13051: "Mike Smith"}

    with patch.object(BlueFolderService, "get_active_user_directory", new=fake_directory):
        result = asyncio.run(cog._build_lookup_member(_DummyUser(id=42, roles=[])))  # type: ignore[arg-type]

    assert "Discord ID: `42`" in result
    assert "Mapped explicitly: Mike Smith (BlueFolder `13051`)" in result


def test_import_technician_mappings_merges_into_file_store(tmp_path) -> None:
    import_path = tmp_path / "suggested.json"
    import_path.write_text('{"suggested_discord_tech_map":{"84":14001}}', encoding="utf-8")
    mapping_file = tmp_path / "technician_mappings.json"
    cog = _build_cog(
        technician_bluefolder_user_map={42: 13051},
        technician_mapping_file=str(mapping_file),
    )

    result = cog._build_import_technician_mappings(str(import_path), mode="merge", confirm=True)

    assert "Imported `1` technician mappings" in result
    assert "Current merged mapping count: `2`" in result
    assert mapping_file.exists()
    assert json.loads(mapping_file.read_text(encoding="utf-8")) == {"42": 13051, "84": 14001}


def test_import_technician_mappings_replace_overwrites_file_store(tmp_path) -> None:
    import_path = tmp_path / "legacy.env"
    import_path.write_text('DISCORD_TECH_MAP={"84":14001}', encoding="utf-8")
    mapping_file = tmp_path / "technician_mappings.json"
    mapping_file.write_text('{"42":13051}', encoding="utf-8")
    cog = _build_cog(technician_mapping_file=str(mapping_file))

    result = cog._build_import_technician_mappings(str(import_path), mode="replace", confirm=True)

    assert "Imported `1` technician mappings" in result
    assert "Mode: `replace`" in result
    assert json.loads(mapping_file.read_text(encoding="utf-8")) == {"84": 14001}


def test_import_technician_mappings_preview_does_not_write(tmp_path) -> None:
    import_path = tmp_path / "suggested.json"
    import_path.write_text('{"suggested_discord_tech_map":{"84":14001}}', encoding="utf-8")
    mapping_file = tmp_path / "technician_mappings.json"
    mapping_file.write_text('{"42":13051}', encoding="utf-8")
    cog = _build_cog(technician_mapping_file=str(mapping_file))

    result = cog._build_import_technician_mappings(str(import_path), mode="merge")

    assert "Preview only. Re-run with `confirm:true` to write these mappings." in result
    assert "Additions: `1`" in result
    assert json.loads(mapping_file.read_text(encoding="utf-8")) == {"42": 13051}


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
