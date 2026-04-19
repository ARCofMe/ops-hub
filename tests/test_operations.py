"""Operations access and mapping tests for Ops Hub."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import io
from types import SimpleNamespace
from unittest.mock import patch

from discord import app_commands
from PIL import Image

from ops_hub.bot.client import OpsHubBot
from ops_hub.bot.cogs.operations import OperationsCog
from ops_hub.core.config import Settings
from ops_hub.core.container import build_container
from ops_hub.models.requests import CommandResult, PhotoAttachmentPayload


@dataclass(slots=True)
class _DummyRole:
    id: int


@dataclass(slots=True)
class _DummyUser:
    id: int
    roles: list[_DummyRole]
    display_name: str = "Mike Smith"

    def __str__(self) -> str:
        return self.display_name


@dataclass(slots=True)
class _DummyInteraction:
    user: _DummyUser
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


class _DummyAttachment:
    filename = "photo.png"
    content_type = "image/png"

    async def read(self) -> bytes:
        image = Image.new("RGB", (16, 16), color=(200, 30, 30))
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()


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


def test_dispatcher_can_view_parts_context_but_not_write_parts_update() -> None:
    cog = _build_cog(dispatcher_user_ids=[42])
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))

    identity = cog._resolve_identity(interaction)

    assert cog._can_view_parts_context(identity) is True
    assert cog._can_write_parts_update(identity) is False
    assert cog._can_log_field_event(identity) is False


def test_admin_can_use_all_operations_surfaces() -> None:
    cog = _build_cog(admin_user_ids=[42])
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))

    identity = cog._resolve_identity(interaction)

    assert cog._can_use_job_commands(identity) is True
    assert cog._can_submit_parts_request(identity) is True
    assert cog._can_use_parts_queue(identity) is True
    assert cog._can_view_parts_context(identity) is True
    assert cog._can_write_parts_issue(identity) is True
    assert cog._can_write_parts_update(identity) is True
    assert cog._can_upload_sr_photo(identity) is True
    assert cog._can_log_field_event(identity) is True


def test_attachment_payload_reads_discord_attachment_shape() -> None:
    cog = _build_cog()

    payload = asyncio.run(cog._attachment_payload(_DummyAttachment()))

    assert isinstance(payload, PhotoAttachmentPayload)
    assert payload.filename == "photo.png"
    assert payload.content_type == "image/png"
    assert payload.data


def test_parts_case_sends_workflow_state_result() -> None:
    cog = _build_cog(parts_user_ids=[42])
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))

    async def fake_describe(self, sr_id: int):
        assert sr_id == 100
        return SimpleNamespace(message="Parts case ready")

    with patch.object(type(cog.bot.container.workflow_state_service), "describe_parts_case", new=fake_describe):
        asyncio.run(cog.parts_case.callback(cog, interaction, sr_id=100))

    assert interaction.response.messages == [{"content": "Parts case ready", "ephemeral": True, "embed": None}]


def test_job_timeline_sends_workflow_state_result() -> None:
    cog = _build_cog(dispatcher_user_ids=[42])
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))

    async def fake_describe(self, sr_id: int):
        assert sr_id == 100
        return SimpleNamespace(message="Timeline ready")

    with patch.object(type(cog.bot.container.workflow_state_service), "describe_service_request_timeline", new=fake_describe):
        asyncio.run(cog.job_timeline.callback(cog, interaction, sr_id=100))

    assert interaction.response.messages == [{"content": "Timeline ready", "ephemeral": True, "embed": None}]


def test_assignments_rejects_technician_override() -> None:
    cog = _build_cog(technician_user_ids=[42], technician_bluefolder_user_map={42: 13051})
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))

    try:
        asyncio.run(cog.assignments.callback(cog, interaction, bluefolder_user_id=13052))
    except app_commands.CheckFailure as exc:
        assert str(exc) == "Only dispatch or admin can request another user's assignments."
    else:
        raise AssertionError("Expected assignment override to be rejected")


def test_route_map_sends_embed_on_success() -> None:
    cog = _build_cog(dispatcher_user_ids=[42])
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))

    async def fake_lookup(self, request):
        assert request.target_bluefolder_user_id == 13051
        return SimpleNamespace(message="Route ready", image_url="https://example.com/map.png")

    with patch.object(type(cog.bot.container.dispatch_service), "lookup_route_map", new=fake_lookup):
        asyncio.run(cog.route_map.callback(cog, interaction, bluefolder_user_id=13051, origin_address=None, destination_address=None))

    assert interaction.response.deferred is True
    assert interaction.followup.messages[0]["content"] == "Route ready"
    assert interaction.followup.messages[0]["ephemeral"] is True
    embed = interaction.followup.messages[0]["embed"]
    assert embed is not None
    assert embed.image.url == "https://example.com/map.png"


def test_route_map_reports_temporary_failure() -> None:
    cog = _build_cog(dispatcher_user_ids=[42])
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))

    async def fake_lookup(self, request):
        raise RuntimeError("downstream error")

    with patch.object(type(cog.bot.container.dispatch_service), "lookup_route_map", new=fake_lookup):
        asyncio.run(cog.route_map.callback(cog, interaction, bluefolder_user_id=None, origin_address=None, destination_address=None))

    assert interaction.response.deferred is True
    assert interaction.followup.messages == [
        {
            "content": "Route map is temporarily unavailable: downstream error",
            "ephemeral": True,
            "embed": None,
        }
    ]


def test_missing_part_passes_identity_and_display_name() -> None:
    cog = _build_cog(technician_user_ids=[42], technician_bluefolder_user_map={42: 13051})
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[], display_name="Mike Tech"))
    captured: dict[str, object] = {}

    async def fake_log_parts_issue(
        self,
        sr_id: int,
        *,
        issue_type: str,
        details: str,
        requested_by_user_id: int,
        requested_by_label: str | None = None,
        bluefolder_user_id: int | None = None,
    ):
        captured.update(
            {
                "sr_id": sr_id,
                "issue_type": issue_type,
                "details": details,
                "requested_by_user_id": requested_by_user_id,
                "requested_by_label": requested_by_label,
                "bluefolder_user_id": bluefolder_user_id,
            }
        )
        return CommandResult(message="logged")

    with patch.object(type(cog.bot.container.bluefolder_service), "log_parts_issue", new=fake_log_parts_issue):
        asyncio.run(cog.missing_part.callback(cog, interaction, sr_id=100, details="Need board"))

    assert captured == {
        "sr_id": 100,
        "issue_type": "missing_part",
        "details": "Need board",
        "requested_by_user_id": 42,
        "requested_by_label": "Mike Tech",
        "bluefolder_user_id": 13051,
    }
    assert interaction.response.messages == [{"content": "logged", "ephemeral": True, "embed": None}]


def test_eta_logs_field_event_and_sends_result() -> None:
    cog = _build_cog(technician_user_ids=[42], technician_bluefolder_user_map={42: 13051})
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[], display_name="Mike Tech"))
    captured: dict[str, object] = {}

    async def fake_log_field_event(
        self,
        sr_id: int,
        *,
        event_type: str,
        requested_by_user_id: int,
        requested_by_label: str | None = None,
        bluefolder_user_id: int | None = None,
        details: str | None = None,
        minutes: int | None = None,
        notify_dispatch: bool = False,
    ):
        captured.update(
            {
                "sr_id": sr_id,
                "event_type": event_type,
                "requested_by_user_id": requested_by_user_id,
                "requested_by_label": requested_by_label,
                "bluefolder_user_id": bluefolder_user_id,
                "details": details,
                "minutes": minutes,
                "notify_dispatch": notify_dispatch,
            }
        )
        return CommandResult(message="eta logged")

    with patch.object(type(cog.bot.container.bluefolder_service), "log_field_event", new=fake_log_field_event):
        asyncio.run(cog.eta.callback(cog, interaction, sr_id=100, minutes=15))

    assert captured == {
        "sr_id": 100,
        "event_type": "eta",
        "requested_by_user_id": 42,
        "requested_by_label": "Mike Tech",
        "bluefolder_user_id": 13051,
        "details": None,
        "minutes": 15,
        "notify_dispatch": True,
    }
    assert interaction.response.messages == [{"content": "eta logged", "ephemeral": True, "embed": None}]


def test_mdlsn_builds_photo_payload_and_uses_display_name() -> None:
    cog = _build_cog(technician_user_ids=[42])
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[], display_name="Mike Tech"))
    attachment = _DummyAttachment()
    captured: dict[str, object] = {}

    async def fake_attach(
        self,
        sr_id: int,
        *,
        photo,
        requested_by_user_id: int,
        requested_by_label: str,
    ):
        captured.update(
            {
                "sr_id": sr_id,
                "photo": photo,
                "requested_by_user_id": requested_by_user_id,
                "requested_by_label": requested_by_label,
            }
        )
        return CommandResult(message="photo attached")

    with patch.object(type(cog.bot.container.photo_ingest_service), "attach_model_serial_photo", new=fake_attach):
        asyncio.run(cog.mdlsn.callback(cog, interaction, sr_id=100, image=attachment))

    assert isinstance(captured["photo"], PhotoAttachmentPayload)
    assert captured["sr_id"] == 100
    assert captured["requested_by_user_id"] == 42
    assert captured["requested_by_label"] == "Mike Tech"
    assert interaction.response.messages == [{"content": "photo attached", "ephemeral": True, "embed": None}]


def test_photo_archive_passes_subject_and_multiple_payloads() -> None:
    cog = _build_cog(technician_user_ids=[42])
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[], display_name="Mike Tech"))
    attachment_a = _DummyAttachment()
    attachment_b = _DummyAttachment()
    captured: dict[str, object] = {}

    async def fake_summary(self, reference: str):
        assert reference == "SR-100"
        return SimpleNamespace(available=True, subject="Dryer repair")

    async def fake_archive(
        self,
        sr_id: int,
        *,
        photos,
        requested_by_user_id: int,
        requested_by_label: str,
        sr_subject: str | None,
    ):
        captured.update(
            {
                "sr_id": sr_id,
                "photos": photos,
                "requested_by_user_id": requested_by_user_id,
                "requested_by_label": requested_by_label,
                "sr_subject": sr_subject,
            }
        )
        return CommandResult(message="archive queued")

    with patch.object(type(cog.bot.container.bluefolder_service), "get_job_summary", new=fake_summary):
        with patch.object(type(cog.bot.container.photo_ingest_service), "archive_job_photos", new=fake_archive):
            asyncio.run(
                cog.photo_archive.callback(
                    cog,
                    interaction,
                    sr_id=100,
                    image_1=attachment_a,
                    image_2=attachment_b,
                    image_3=None,
                    image_4=None,
                )
            )

    assert captured["sr_id"] == 100
    assert captured["requested_by_user_id"] == 42
    assert captured["requested_by_label"] == "Mike Tech"
    assert captured["sr_subject"] == "Dryer repair"
    assert len(captured["photos"]) == 2
    assert all(isinstance(photo, PhotoAttachmentPayload) for photo in captured["photos"])
    assert interaction.response.messages == [{"content": "archive queued", "ephemeral": True, "embed": None}]


def test_part_ordered_builds_expected_metadata() -> None:
    cog = _build_cog(parts_user_ids=[42])
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[], display_name="Parts User"))
    captured: dict[str, object] = {}

    async def fake_log_update(
        self,
        sr_id: int,
        *,
        update_type: str,
        details: str,
        requested_by_user_id: int,
        requested_by_label: str | None = None,
        bluefolder_user_id: int | None = None,
        metadata: dict[str, str] | None = None,
    ):
        captured.update(
            {
                "sr_id": sr_id,
                "update_type": update_type,
                "details": details,
                "requested_by_user_id": requested_by_user_id,
                "requested_by_label": requested_by_label,
                "bluefolder_user_id": bluefolder_user_id,
                "metadata": metadata,
            }
        )
        return CommandResult(message="ordered logged")

    with patch.object(type(cog.bot.container.bluefolder_service), "log_parts_update", new=fake_log_update):
        asyncio.run(
            cog.part_ordered.callback(
                cog,
                interaction,
                sr_id=100,
                vendor="Marcone",
                eta="Friday",
                details=None,
            )
        )

    assert captured == {
        "sr_id": 100,
        "update_type": "part_ordered",
        "details": "Order submitted.",
        "requested_by_user_id": 42,
        "requested_by_label": "Parts User",
        "bluefolder_user_id": None,
        "metadata": {"vendor": "Marcone", "eta": "Friday"},
    }
    assert interaction.response.messages == [{"content": "ordered logged", "ephemeral": True, "embed": None}]


def test_part_request_builds_tracked_request_payload() -> None:
    cog = _build_cog(technician_user_ids=[42], technician_bluefolder_user_map={42: 13051})
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))
    captured: dict[str, object] = {}

    async def fake_create(self, payload):
        captured["payload"] = payload
        return CommandResult(message="request created")

    with patch.object(type(cog.bot.container.parts_cannon_service), "create_request", new=fake_create):
        asyncio.run(cog.part_request.callback(cog, interaction, reference="SR-100", description="Need control board"))

    payload = captured["payload"]
    assert isinstance(payload, type(payload))
    assert payload.reference == "SR-100"
    assert payload.description == "Need control board"
    assert payload.requested_by_user_id == 42
    assert payload.technician_bluefolder_user_id == 13051
    assert payload.requester_is_admin is False
    assert interaction.response.messages == [{"content": "request created", "ephemeral": True, "embed": None}]


def test_part_update_builds_request_update_payload() -> None:
    cog = _build_cog(parts_user_ids=[42])
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))
    captured: dict[str, object] = {}

    async def fake_update(self, payload):
        captured["payload"] = payload
        return CommandResult(message="request updated")

    with patch.object(type(cog.bot.container.parts_cannon_service), "update_request", new=fake_update):
        asyncio.run(cog.part_update.callback(cog, interaction, request_id=7, status="ordered"))

    payload = captured["payload"]
    assert payload.request_id == 7
    assert payload.status == "ordered"
    assert payload.updated_by_user_id == 42
    assert interaction.response.messages == [{"content": "request updated", "ephemeral": True, "embed": None}]


def test_parts_recommend_sends_supported_evidence_only() -> None:
    cog = _build_cog(parts_user_ids=[42])
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))

    async def fake_recommendation(self, sr_id: int):
        assert sr_id == 100
        return {
            "available": True,
            "srId": "100",
            "conversation": {
                "supportedPartRecommendations": [
                    {"item": "FAN-1", "itemType": "part", "matchingRequestCount": 2, "score": 0.5}
                ],
                "diagnosticQuestions": ["Is the evaporator fan running?"],
                "unsupportedPartsPolicy": "Do not present unsupported parts as recommendations.",
            },
        }

    with patch.object(
        type(cog.bot.container.parts_cannon_service),
        "get_recommendation_conversation_payload",
        new=fake_recommendation,
    ):
        asyncio.run(cog.parts_recommend.callback(cog, interaction, sr_id=100))

    content = interaction.response.messages[0]["content"]
    assert "PartsCannon evidence for SR 100" in content
    assert "FAN-1 | part | 2 matching SRs | 50% match" in content
    assert "Is the evaporator fan running?" in content
    assert "Do not present unsupported parts as recommendations." in content
    assert interaction.response.messages[0]["ephemeral"] is True


def test_part_claim_and_unclaim_build_claim_payloads() -> None:
    cog = _build_cog(parts_user_ids=[42])
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))
    captured: list[object] = []

    async def fake_claim(self, payload):
        captured.append(payload)
        return CommandResult(message="claim updated")

    with patch.object(type(cog.bot.container.parts_cannon_service), "claim_request", new=fake_claim):
        asyncio.run(cog.part_claim.callback(cog, interaction, request_id=7))
        asyncio.run(cog.part_unclaim.callback(cog, interaction, request_id=7))

    assert len(captured) == 2
    assert captured[0].request_id == 7
    assert captured[0].parts_user_id == 42
    assert captured[0].updated_by_user_id == 42
    assert captured[1].request_id == 7
    assert captured[1].parts_user_id is None
    assert captured[1].updated_by_user_id == 42
    assert interaction.response.messages == [
        {"content": "claim updated", "ephemeral": True, "embed": None},
        {"content": "claim updated", "ephemeral": True, "embed": None},
    ]


def test_part_sync_and_reconcile_send_results() -> None:
    cog = _build_cog(parts_user_ids=[42])
    interaction = _DummyInteraction(user=_DummyUser(id=42, roles=[]))

    async def fake_sync(self):
        return CommandResult(message="sync complete")

    async def fake_reconcile(self):
        return CommandResult(message="reconcile complete")

    with patch.object(type(cog.bot.container.parts_cannon_service), "sync_requests_to_parts_system", new=fake_sync):
        with patch.object(type(cog.bot.container.parts_cannon_service), "reconcile_requests_from_parts_system", new=fake_reconcile):
            asyncio.run(cog.part_sync.callback(cog, interaction))
            asyncio.run(cog.part_reconcile.callback(cog, interaction))

    assert interaction.response.messages == [
        {"content": "sync complete", "ephemeral": True, "embed": None},
        {"content": "reconcile complete", "ephemeral": True, "embed": None},
    ]
