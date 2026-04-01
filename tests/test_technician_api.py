"""Technician API service tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from ops_hub.models.requests import ArchivedPhotoRecord, PhotoComplianceSummary
from ops_hub.services.technician_api import TechnicianApiService


def test_resolve_technician_uses_mapping_subject() -> None:
    service = TechnicianApiService(
        bluefolder_service=SimpleNamespace(),
        technician_directory_service=SimpleNamespace(mappings=lambda: {123: 9001}),
        parts_cannon_service=SimpleNamespace(),
        photo_ingest_service=SimpleNamespace(),
        workflow_state_service=SimpleNamespace(),
    )

    assert service.resolve_technician(token_subject="123") == (123, 9001)
    assert service.resolve_technician(token_subject="999") is None


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
            result=SimpleNamespace(stage_label="Ready for Scheduling", next_action="Call customer to schedule."),
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
