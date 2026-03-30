"""Admin/debug command rendering tests for Ops Hub."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import patch

from ops_hub.bot.client import OpsHubBot
from ops_hub.services.bluefolder import BlueFolderService
from ops_hub.bot.cogs.admin import AdminCog, _build_tech_map_suggestion, _parse_mapping_import_text
from ops_hub.core.config import Settings
from ops_hub.core.container import build_container
from ops_hub.models.requests import AttentionItemRecord, WorkflowStateSnapshot


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
    name: str = "Technician"


@dataclass(slots=True)
class _DummyUser:
    id: int
    roles: list[_DummyRole]
    name: str = "mike.smith"
    display_name: str = "Mike Smith"
    global_name: str | None = "Mike Smith"
    bot: bool = False


@dataclass(slots=True)
class _DummyChannel:
    members: list[_DummyUser]


@dataclass(slots=True)
class _DummyInteraction:
    user: _DummyUser
    guild: object | None = None
    channel: object | None = None
    guild_id: int | None = 123456
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


def test_build_ops_status_reports_basic_runtime_state() -> None:
    cog = _build_cog()

    result = cog._build_ops_status()

    assert "Ops Hub Status" in result
    assert "Environment: `dev`" in result
    assert "Guild sync: guild" in result
    assert "Configured guild id: `123456`" in result
    assert "Workflow policy runner: disabled" in result
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
    assert "Photo ingest: `unconfigured`" in result
    assert "Photo ingest mode: `dormant`" in result
    assert "Photo ingest listener: `configured`" in result
    assert "Photo ingest upload: `unconfigured`" in result
    assert "Photo ingest archive: `unconfigured`" in result
    assert "Photo ingest mailbox: `unconfigured`" in result
    assert "Photo features:" in result
    assert "`mdlsn_upload`: `enabled` via `env`" in result
    assert "Notifications: `dry_run` via `logger`" in result
    assert "Notification notices sent: `0`" in result
    assert "Workflow attention items: `0`" in result
    assert "Workflow parts cases: `0`" in result
    assert "Workflow events: `0`" in result
    assert "Workflow attention status: unavailable" in result
    assert "Workflow urgent state: open `0`, suppressed `0`" in result


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


def test_build_policy_status_renders_current_snapshot() -> None:
    cog = _build_cog(enable_workflow_policy_runner=True, workflow_policy_interval_seconds=300)
    cog.bot.container.workflow_state_service.store.save(
        WorkflowStateSnapshot(
            updated_at="2026-03-29T10:00:00+00:00",
            attention_items=[
                AttentionItemRecord(
                    item_id="dispatch:SR-100:part_ready",
                    sr_id=100,
                    reference="SR-100",
                    category="dispatch",
                    status="open",
                    stage="part_ready",
                    stage_label="Ready for Scheduling",
                    age_bucket="urgent",
                    age_hours=80,
                    summary="Dryer repair",
                    next_action="Schedule return visit.",
                    assigned_owner_discord_user_id=42,
                ),
                AttentionItemRecord(
                    item_id="dispatch:SR-101:part_received",
                    sr_id=101,
                    reference="SR-101",
                    category="dispatch",
                    status="snoozed",
                    stage="part_received",
                    stage_label="Received",
                    age_bucket="urgent",
                    age_hours=90,
                    summary="Washer repair",
                )
            ],
            parts_cases=[],
            events=[],
        )
    )

    result = asyncio.run(cog._build_policy_status())

    assert "Workflow Policy Status" in result
    assert "Runner: enabled every `300`s" in result
    assert "Urgent open items: `1`" in result
    assert "Urgent suppressed items: `1`" in result
    assert "Queue status" in result
    assert "open: `1`" in result
    assert "snoozed: `1`" in result
    assert "Assigned owners: `1`" in result
    assert "Unassigned owners: `1`" in result
    assert "`SR-100` `Ready for Scheduling` `80h`" in result


def test_build_policy_preview_does_not_send_notices() -> None:
    cog = _build_cog()

    result = asyncio.run(cog._build_policy_preview())

    assert "Workflow Policy Preview" in result
    assert "Topics routed: `0`" in result or "Topics routed: `1`" in result
    assert "Notices sent: `0`" in result
    assert asyncio.run(cog.bot.container.notification_service.status()).notice_count == 0


def test_build_technician_mappings_renders_current_map() -> None:
    cog = _build_cog(technician_bluefolder_user_map={42: 13051})

    result = cog._build_technician_mappings()

    assert "Technician Mappings" in result
    assert "<@42> (BlueFolder `13051`)" in result


def test_build_command_access_describes_current_scopes() -> None:
    cog = _build_cog()

    result = cog._build_command_access()

    assert "`/ops_status`" in result
    assert "`/policy_status`" in result
    assert "`/policy_preview`" in result
    assert "`/policy_run_now`" in result
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
    assert "`/tech_assignments`, `/tech_job`, `/dispatch_board`, `/dispatch_attention`, `/attention_ack`, `/attention_snooze`, `/attention_assign`, `/attention_clear_owner`, `/attention_unsnooze`, `/attention_reopen`, `/attention_history`, `/dispatch_next`, `/photo_compliance_board`: dispatchers, admins" in result
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


def test_collect_members_uses_channel_scope_without_bots() -> None:
    cog = _build_cog()
    interaction = _DummyInteraction(
        user=_DummyUser(id=1, roles=[]),
        guild=object(),
        channel=_DummyChannel(
            members=[
                _DummyUser(id=42, roles=[_DummyRole(id=7, name="Technician")]),
                _DummyUser(id=43, roles=[_DummyRole(id=9, name="Admin")], bot=True),
            ]
        ),
    )

    result = asyncio.run(cog._collect_members(interaction, scope="channel"))  # type: ignore[arg-type]

    assert result == [
        {
            "discord_user_id": "42",
            "username": "mike.smith",
            "display_name": "Mike Smith",
            "global_name": "Mike Smith",
            "role_names": ["Technician"],
        }
    ]


def test_collect_members_reports_guild_fetch_failure() -> None:
    cog = _build_cog()

    class _FailingGuild:
        async def fetch_members(self, *, limit=None):
            raise RuntimeError("no intent")
            yield  # pragma: no cover

    interaction = _DummyInteraction(
        user=_DummyUser(id=1, roles=[]),
        guild=_FailingGuild(),
    )

    try:
        asyncio.run(cog._collect_members(interaction, scope="guild"))  # type: ignore[arg-type]
    except RuntimeError as exc:
        assert str(exc) == "Could not load Discord guild members. Check Server Members Intent and bot permissions."
    else:
        raise AssertionError("Expected guild member collection failure to be raised")


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


def test_admin_cog_service_status_uses_deferred_followup() -> None:
    cog = _build_cog(admin_user_ids=[42])
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))

    async def fake_build(self) -> str:
        return "Service status ready"

    with patch.object(AdminCog, "_build_service_status", new=fake_build):
        asyncio.run(cog.service_status.callback(cog, interaction))

    assert interaction.response.deferred is True
    assert interaction.followup.messages == [{"content": "Service status ready", "ephemeral": True, "embed": None}]


def test_admin_cog_policy_status_uses_deferred_followup() -> None:
    cog = _build_cog(admin_user_ids=[42])
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))

    async def fake_build(self) -> str:
        return "Policy status ready"

    with patch.object(AdminCog, "_build_policy_status", new=fake_build):
        asyncio.run(cog.policy_status.callback(cog, interaction))

    assert interaction.response.deferred is True
    assert interaction.followup.messages == [{"content": "Policy status ready", "ephemeral": True, "embed": None}]


def test_admin_cog_policy_preview_uses_deferred_followup() -> None:
    cog = _build_cog(admin_user_ids=[42])
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))

    async def fake_build(self) -> str:
        return "Policy preview ready"

    with patch.object(AdminCog, "_build_policy_preview", new=fake_build):
        asyncio.run(cog.policy_preview.callback(cog, interaction))

    assert interaction.response.deferred is True
    assert interaction.followup.messages == [{"content": "Policy preview ready", "ephemeral": True, "embed": None}]


def test_admin_cog_policy_run_now_uses_deferred_followup() -> None:
    cog = _build_cog(admin_user_ids=[42])
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))

    async def fake_build(self) -> str:
        return "Policy run ready"

    with patch.object(AdminCog, "_build_policy_run_now", new=fake_build):
        asyncio.run(cog.policy_run_now.callback(cog, interaction))

    assert interaction.response.deferred is True
    assert interaction.followup.messages == [{"content": "Policy run ready", "ephemeral": True, "embed": None}]


def test_admin_cog_export_member_map_uses_deferred_followup() -> None:
    cog = _build_cog(admin_user_ids=[42])
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))

    async def fake_build(self, interaction, scope: str) -> str:
        assert scope == "channel"
        return "Member export ready"

    with patch.object(AdminCog, "_build_export_member_map", new=fake_build):
        asyncio.run(cog.export_member_map.callback(cog, interaction, scope="channel"))

    assert interaction.response.deferred is True
    assert interaction.followup.messages == [{"content": "Member export ready", "ephemeral": True, "embed": None}]


def test_admin_cog_import_technician_mappings_sends_response() -> None:
    cog = _build_cog(admin_user_ids=[42])
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))

    with patch.object(
        AdminCog,
        "_build_import_technician_mappings",
        return_value="Import preview",
    ) as build_import:
        asyncio.run(
            cog.import_technician_mappings.callback(
                cog,
                interaction,
                path="/tmp/map.json",
                mode="merge",
                confirm=False,
            )
        )

    build_import.assert_called_once_with("/tmp/map.json", mode="merge", confirm=False)
    assert interaction.response.messages == [{"content": "Import preview", "ephemeral": True, "embed": None}]


def test_admin_cog_lookup_member_uses_deferred_followup() -> None:
    cog = _build_cog(admin_user_ids=[42])
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))
    target = _DummyUser(id=84, roles=[])

    async def fake_build(self, user) -> str:
        assert user.id == 84
        return "Lookup ready"

    with patch.object(AdminCog, "_build_lookup_member", new=fake_build):
        asyncio.run(cog.lookup_member.callback(cog, interaction, user=target))  # type: ignore[arg-type]

    assert interaction.response.deferred is True
    assert interaction.followup.messages == [{"content": "Lookup ready", "ephemeral": True, "embed": None}]
