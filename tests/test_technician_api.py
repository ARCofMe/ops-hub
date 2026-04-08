"""Technician API service tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
import base64

from ops_hub.models.requests import ArchivedPhotoRecord, PhotoComplianceSummary
from ops_hub.services.technician_api import TechnicianApiService


def test_resolve_technician_uses_mapping_subject() -> None:
    service = TechnicianApiService(
        bluefolder_service=SimpleNamespace(),
        technician_directory_service=SimpleNamespace(
            mappings=lambda: {123: 9001},
            technician_display_label=lambda **kwargs: "Mapped Tech" if kwargs.get("bluefolder_user_id") == 9001 else f"Tech {kwargs.get('bluefolder_user_id')}",
        ),
        parts_cannon_service=SimpleNamespace(),
        photo_ingest_service=SimpleNamespace(),
        workflow_state_service=SimpleNamespace(),
    )

    resolved = service.resolve_technician(token_subject="123")
    assert resolved is not None
    assert resolved.discord_user_id == 123
    assert resolved.bluefolder_user_id == 9001
    fallback = service.resolve_technician(token_subject="999")
    assert fallback is not None
    assert fallback.discord_user_id is None
    assert fallback.bluefolder_user_id == 999


def test_resolve_technician_accepts_bluefolder_subject_without_mapping() -> None:
    service = TechnicianApiService(
        bluefolder_service=SimpleNamespace(),
        technician_directory_service=SimpleNamespace(
            mappings=lambda: {},
            technician_display_label=lambda **kwargs: "Field Sam" if kwargs.get("bluefolder_user_id") == 9001 else None,
        ),
        parts_cannon_service=SimpleNamespace(),
        photo_ingest_service=SimpleNamespace(),
        workflow_state_service=SimpleNamespace(),
    )

    resolved = service.resolve_technician(technician_id="9001")

    assert resolved is not None
    assert resolved.discord_user_id is None
    assert resolved.bluefolder_user_id == 9001
    assert resolved.actor_label == "Field Sam"


def test_get_today_normalizes_assignment_shape() -> None:
    bluefolder = SimpleNamespace(
        get_assignments_for_user_today=lambda user_id: asyncio.sleep(
            0, result=[{"serviceRequestId": "100", "address": "123 Main", "subject": "Washer", "status": "Pending"}]
        )
    )
    service = TechnicianApiService(
        bluefolder_service=bluefolder,
        technician_directory_service=SimpleNamespace(mappings=lambda: {123: 9001}),
        parts_cannon_service=SimpleNamespace(),
        photo_ingest_service=SimpleNamespace(),
        workflow_state_service=SimpleNamespace(),
    )

    jobs = asyncio.run(service.get_today(technician_bluefolder_user_id=9001))

    assert jobs == [
        {
            "id": "100",
            "address": "123 Main",
            "appointmentWindow": "Unscheduled",
            "customerName": "Washer",
            "customerPhone": "",
            "status": "Pending",
            "statusMeta": None,
            "distanceMiles": None,
            "equipment": None,
        }
    ]


def test_submit_note_requires_text() -> None:
    service = TechnicianApiService(
        bluefolder_service=SimpleNamespace(),
        technician_directory_service=SimpleNamespace(mappings=lambda: {}),
        parts_cannon_service=SimpleNamespace(),
        photo_ingest_service=SimpleNamespace(),
        workflow_state_service=SimpleNamespace(),
    )

    result = asyncio.run(
        service.submit_note(
            sr_id=100,
            note="   ",
            technician_discord_user_id=1,
            technician_bluefolder_user_id=2,
        )
    )

    assert result == {"success": False, "message": "A note is required."}


def test_get_job_includes_parts_case_fields() -> None:
    bluefolder = SimpleNamespace(
        describe_service_request_status=lambda status: {"raw": status, "categoryLabel": "Scheduling", "isScheduling": True},
        get_job_summary=lambda reference: asyncio.sleep(
            0,
            result=SimpleNamespace(
                available=True,
                service_request_id="100",
                address="123 Main",
                city="Portland",
                state="ME",
                postal_code="04101",
                customer_name="Pat",
                customer_phone="555-0100",
                service_request_status="Scheduled",
            ),
        )
    )
    workflow_state = SimpleNamespace(
        get_parts_case=lambda sr_id: asyncio.sleep(
            0,
            result=SimpleNamespace(
                stage_label="Ready for Scheduling",
                next_action="Call customer to schedule.",
                service_request_status="Scheduled",
            ),
        )
    )
    service = TechnicianApiService(
        bluefolder_service=bluefolder,
        technician_directory_service=SimpleNamespace(mappings=lambda: {}),
        parts_cannon_service=SimpleNamespace(),
        photo_ingest_service=SimpleNamespace(),
        workflow_state_service=workflow_state,
    )

    payload = asyncio.run(service.get_job(sr_id=100))

    assert payload["partsStage"] == "Ready for Scheduling"
    assert payload["nextAction"] == "Call customer to schedule."
    assert payload["statusMeta"]["categoryLabel"] == "Scheduling"


def test_upload_job_photo_attaches_photo_payload() -> None:
    captured: dict[str, object] = {}

    async def attach_job_photo(sr_id: int, **kwargs):
        captured["sr_id"] = sr_id
        captured.update(kwargs)
        return SimpleNamespace(message="Photo attached")

    service = TechnicianApiService(
        bluefolder_service=SimpleNamespace(),
        technician_directory_service=SimpleNamespace(mappings=lambda: {}),
        parts_cannon_service=SimpleNamespace(),
        photo_ingest_service=SimpleNamespace(attach_job_photo=attach_job_photo),
        workflow_state_service=SimpleNamespace(),
    )

    payload = asyncio.run(
        service.upload_job_photo(
            sr_id=100,
            label="Model / Serial",
            filename="tag.jpg",
            content_type="image/jpeg",
            data_base64=base64.b64encode(b"jpeg-bytes").decode("ascii"),
            technician_discord_user_id=None,
            technician_bluefolder_user_id=9001,
            technician_actor_label="Field Sam",
        )
    )

    assert payload == {"success": True, "message": "Photo attached"}
    assert captured["sr_id"] == 100
    assert captured["label"] == "MODEL / SERIAL"
    assert captured["requested_by_user_id"] == 9001
    assert captured["requested_by_label"] == "Field Sam"
    assert captured["photo"].filename == "tag.jpg"
    assert captured["photo"].data == b"jpeg-bytes"


def test_log_call_ahead_defaults_to_thirty_minutes() -> None:
    calls: list[dict[str, object]] = []

    async def log_route_update(sr_id: int, **kwargs):
        calls.append({"sr_id": sr_id, **kwargs})
        return SimpleNamespace(message="ETA logged")

    service = TechnicianApiService(
        bluefolder_service=SimpleNamespace(log_route_update=log_route_update),
        technician_directory_service=SimpleNamespace(mappings=lambda: {}),
        parts_cannon_service=SimpleNamespace(),
        photo_ingest_service=SimpleNamespace(),
        workflow_state_service=SimpleNamespace(),
    )

    result = asyncio.run(
        service.log_call_ahead(sr_id=100, technician_discord_user_id=1, technician_bluefolder_user_id=2)
    )

    assert result["success"] is True
    assert result["callAheadMinutes"] == 30
    assert calls[0]["minutes"] == 30
    assert calls[0]["notify_dispatch"] is True


def test_update_status_supports_start() -> None:
    calls: list[dict[str, object]] = []

    async def log_field_event(sr_id: int, **kwargs):
        calls.append({"sr_id": sr_id, **kwargs})
        return SimpleNamespace(message="Start logged")

    service = TechnicianApiService(
        bluefolder_service=SimpleNamespace(log_field_event=log_field_event),
        technician_directory_service=SimpleNamespace(mappings=lambda: {}),
        parts_cannon_service=SimpleNamespace(),
        photo_ingest_service=SimpleNamespace(),
        workflow_state_service=SimpleNamespace(),
    )

    result = asyncio.run(
        service.update_status(
            sr_id=100,
            technician_discord_user_id=1,
            technician_bluefolder_user_id=2,
            status="start",
        )
    )

    assert result == {"success": True, "message": "Start logged"}
    assert calls[0]["event_type"] == "start"
    assert calls[0]["notify_dispatch"] is True


def test_log_work_start_includes_optional_details() -> None:
    calls: list[dict[str, object]] = []

    async def log_field_event(sr_id: int, **kwargs):
        calls.append({"sr_id": sr_id, **kwargs})
        return SimpleNamespace(message="Start logged")

    service = TechnicianApiService(
        bluefolder_service=SimpleNamespace(log_field_event=log_field_event),
        technician_directory_service=SimpleNamespace(mappings=lambda: {}),
        parts_cannon_service=SimpleNamespace(),
        photo_ingest_service=SimpleNamespace(),
        workflow_state_service=SimpleNamespace(),
    )

    result = asyncio.run(
        service.log_work_start(
            sr_id=100,
            details="Verified unit power and started diagnostic.",
            technician_discord_user_id=1,
            technician_bluefolder_user_id=2,
        )
    )

    assert result == {"success": True, "message": "Start logged"}
    assert calls[0]["event_type"] == "start"
    assert calls[0]["details"] == "Verified unit power and started diagnostic."


def test_preview_closeout_returns_labor_preview() -> None:
    async def preview_technician_closeout(draft):
        assert draft.labor_code == "oow_hourly"
        return {
            "laborCode": draft.labor_code,
            "laborLabel": "OOW Hourly Labor",
            "billable": True,
            "dateWorked": "2026.04.08",
            "startTime": "8:00 AM",
            "endTime": "9:30 AM",
            "durationMinutes": 90,
            "durationLabel": "1:30",
            "workPerformed": "Replaced failed inlet valve and verified fill.",
            "signoffLabel": "Customer approved and signed by Pat Customer.",
        }

    service = TechnicianApiService(
        bluefolder_service=SimpleNamespace(preview_technician_closeout=preview_technician_closeout),
        technician_directory_service=SimpleNamespace(mappings=lambda: {}),
        parts_cannon_service=SimpleNamespace(),
        photo_ingest_service=SimpleNamespace(),
        workflow_state_service=SimpleNamespace(),
    )

    payload = asyncio.run(
        service.preview_closeout(
            sr_id=100,
            technician_discord_user_id=None,
            technician_bluefolder_user_id=9001,
            labor_code="oow_hourly",
            work_performed="Replaced failed inlet valve and verified fill.",
            started_at_epoch_ms=1,
            ended_at_epoch_ms=2,
            duration_minutes=90,
            signed_by="Pat Customer",
            customer_approved=True,
            final_outcome="completed",
        )
    )

    assert payload["success"] is True
    assert payload["laborLabel"] == "OOW Hourly Labor"
    assert payload["durationLabel"] == "1:30"


def test_submit_closeout_logs_complete_after_labor_submission() -> None:
    labor_calls: list[dict[str, object]] = []
    complete_calls: list[dict[str, object]] = []

    async def submit_technician_closeout(draft, **kwargs):
        labor_calls.append({"draft": draft, **kwargs})
        return SimpleNamespace(message="Closeout submitted with `OOW Hourly Labor` for `1:30`.")

    async def log_field_event(sr_id: int, **kwargs):
        complete_calls.append({"sr_id": sr_id, **kwargs})
        return SimpleNamespace(message="Complete logged")

    service = TechnicianApiService(
        bluefolder_service=SimpleNamespace(
            submit_technician_closeout=submit_technician_closeout,
            log_field_event=log_field_event,
        ),
        technician_directory_service=SimpleNamespace(
            mappings=lambda: {},
            technician_display_label=lambda **kwargs: "Field Sam",
        ),
        parts_cannon_service=SimpleNamespace(),
        photo_ingest_service=SimpleNamespace(),
        workflow_state_service=SimpleNamespace(),
    )

    payload = asyncio.run(
        service.submit_closeout(
            sr_id=100,
            technician_discord_user_id=None,
            technician_bluefolder_user_id=9001,
            technician_actor_label="Field Sam",
            labor_code="oow_hourly",
            work_performed="Replaced failed inlet valve and verified fill.",
            started_at_epoch_ms=1,
            ended_at_epoch_ms=2,
            duration_minutes=90,
            signed_by="Pat Customer",
            customer_approved=True,
            final_outcome="completed",
            outcome_note="Unit tested good after repair.",
        )
    )

    assert payload["success"] is True
    assert "Closeout submitted" in payload["message"]
    assert labor_calls[0]["bluefolder_user_id"] == 9001
    assert complete_calls[0]["event_type"] == "complete"


def test_report_no_answer_logs_field_event() -> None:
    calls: list[dict[str, object]] = []

    async def log_field_event(sr_id: int, **kwargs):
        calls.append({"sr_id": sr_id, **kwargs})
        return SimpleNamespace(message="No-answer logged")

    service = TechnicianApiService(
        bluefolder_service=SimpleNamespace(log_field_event=log_field_event),
        technician_directory_service=SimpleNamespace(mappings=lambda: {}),
        parts_cannon_service=SimpleNamespace(),
        photo_ingest_service=SimpleNamespace(),
        workflow_state_service=SimpleNamespace(),
    )

    result = asyncio.run(
        service.report_no_answer(
            sr_id=100,
            details="Called twice, voicemail full.",
            technician_discord_user_id=1,
            technician_bluefolder_user_id=2,
        )
    )

    assert result == {"success": True, "message": "No-answer logged"}
    assert calls[0]["event_type"] == "no_answer"
    assert calls[0]["notify_dispatch"] is True


def test_report_not_home_logs_field_event() -> None:
    calls: list[dict[str, object]] = []

    async def log_field_event(sr_id: int, **kwargs):
        calls.append({"sr_id": sr_id, **kwargs})
        return SimpleNamespace(message="Not-home logged")

    service = TechnicianApiService(
        bluefolder_service=SimpleNamespace(log_field_event=log_field_event),
        technician_directory_service=SimpleNamespace(mappings=lambda: {}),
        parts_cannon_service=SimpleNamespace(),
        photo_ingest_service=SimpleNamespace(),
        workflow_state_service=SimpleNamespace(),
    )

    result = asyncio.run(
        service.report_not_home(
            sr_id=100,
            details="No vehicle in driveway.",
            technician_discord_user_id=1,
            technician_bluefolder_user_id=2,
        )
    )

    assert result == {"success": True, "message": "Not-home logged"}
    assert calls[0]["event_type"] == "not_home"
    assert calls[0]["notify_dispatch"] is True


def test_report_quote_needed_logs_note_and_workflow_event() -> None:
    note_calls: list[dict[str, object]] = []
    workflow_events: list[dict[str, object]] = []

    async def log_field_event(sr_id: int, **kwargs):
        note_calls.append({"sr_id": sr_id, **kwargs})
        return SimpleNamespace(message="Quote note logged")

    workflow_state = SimpleNamespace(record_event=lambda **kwargs: workflow_events.append(kwargs))
    service = TechnicianApiService(
        bluefolder_service=SimpleNamespace(log_field_event=log_field_event),
        technician_directory_service=SimpleNamespace(mappings=lambda: {}),
        parts_cannon_service=SimpleNamespace(),
        photo_ingest_service=SimpleNamespace(),
        workflow_state_service=workflow_state,
    )

    result = asyncio.run(
        service.report_quote_needed(
            sr_id=100,
            details="Landlord must approve COD repair.",
            subtype="landlord",
            technician_discord_user_id=1,
            technician_bluefolder_user_id=2,
        )
    )

    assert result["quoteSubtype"] == "landlord"
    assert "Quote needed (landlord)" in note_calls[0]["details"]
    assert workflow_events[0]["event_type"] == "quote_needed_reported"
    assert workflow_events[0]["metadata"] == {"quote_subtype": "landlord"}


def test_report_reschedule_needed_requires_reason() -> None:
    service = TechnicianApiService(
        bluefolder_service=SimpleNamespace(),
        technician_directory_service=SimpleNamespace(mappings=lambda: {}),
        parts_cannon_service=SimpleNamespace(),
        photo_ingest_service=SimpleNamespace(),
        workflow_state_service=SimpleNamespace(),
    )

    result = asyncio.run(
        service.report_reschedule_needed(
            sr_id=100,
            reason="   ",
            technician_discord_user_id=1,
            technician_bluefolder_user_id=2,
        )
    )

    assert result == {"success": False, "message": "A reschedule reason is required."}


def test_report_unable_to_complete_logs_event_and_workflow_record() -> None:
    note_calls: list[dict[str, object]] = []
    workflow_events: list[dict[str, object]] = []

    async def log_field_event(sr_id: int, **kwargs):
        note_calls.append({"sr_id": sr_id, **kwargs})
        return SimpleNamespace(message="Unable-to-complete logged")

    workflow_state = SimpleNamespace(record_event=lambda **kwargs: workflow_events.append(kwargs))
    service = TechnicianApiService(
        bluefolder_service=SimpleNamespace(log_field_event=log_field_event),
        technician_directory_service=SimpleNamespace(mappings=lambda: {}),
        parts_cannon_service=SimpleNamespace(),
        photo_ingest_service=SimpleNamespace(),
        workflow_state_service=workflow_state,
    )

    result = asyncio.run(
        service.report_unable_to_complete(
            sr_id=100,
            reason="Vendor portal outage blocked warranty closeout.",
            technician_discord_user_id=1,
            technician_bluefolder_user_id=2,
        )
    )

    assert result == {"success": True, "message": "Unable-to-complete logged"}
    assert note_calls[0]["event_type"] == "unable_to_complete"
    assert workflow_events[0]["event_type"] == "unable_to_complete_reported"


def test_get_job_photo_status_returns_structured_payload() -> None:
    async def get_photo_compliance_summary(sr_id: int):
        return PhotoComplianceSummary(
            sr_id=sr_id,
            mailbox_status="present",
            message="Found matching archived photos.",
            matched_records=[
                ArchivedPhotoRecord(
                    subject="SR-100 photos",
                    from_email="tech@example.com",
                    received_at="2026-03-31T08:30:00Z",
                    attachment_count=4,
                    attachment_names=["sr100-tag.jpg"],
                )
            ],
            total_photos=4,
            found_tags=["before", "after"],
            missing_tags=["tag"],
        )

    async def evaluate_photo_reminder(sr_id: int, *, status_override=None, send_notice=False):
        _ = (sr_id, status_override, send_notice)
        return SimpleNamespace(message="Should notify: `yes`\nReason: Missing required archived photos.")

    photo_ingest = SimpleNamespace(
        feature_flags=SimpleNamespace(is_enabled=lambda flag: flag == "photo_mailbox_scan"),
        adapter=SimpleNamespace(get_photo_compliance_summary=get_photo_compliance_summary),
        evaluate_photo_reminder=evaluate_photo_reminder,
    )
    service = TechnicianApiService(
        bluefolder_service=SimpleNamespace(),
        technician_directory_service=SimpleNamespace(mappings=lambda: {}),
        parts_cannon_service=SimpleNamespace(),
        photo_ingest_service=photo_ingest,
        workflow_state_service=SimpleNamespace(),
    )

    payload = asyncio.run(service.get_job_photo_status(sr_id=100))

    assert payload["enabled"] is True
    assert payload["mailboxStatus"] == "present"
    assert payload["shouldNotify"] is True
    assert payload["records"][0]["attachmentCount"] == 4
    assert payload["reason"] == "Missing required archived photos."
