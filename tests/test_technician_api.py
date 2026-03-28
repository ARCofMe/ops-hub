"""Technician API service tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from ops_hub.services.technician_api import TechnicianApiService


def test_resolve_technician_uses_mapping_subject() -> None:
    service = TechnicianApiService(
        bluefolder_service=SimpleNamespace(),
        technician_directory_service=SimpleNamespace(mappings=lambda: {123: 9001}),
        parts_cannon_service=SimpleNamespace(),
        photo_ingest_service=SimpleNamespace(),
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
