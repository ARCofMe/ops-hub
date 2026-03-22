"""Parts request lifecycle tests for Ops Hub."""

from __future__ import annotations

import asyncio

from ops_hub.integrations.parts_cannon_adapter import PartsCannonAdapter
from ops_hub.models.requests import PartRequestCreate, PartRequestUpdate
from ops_hub.services.notifications import NotificationService
from ops_hub.services.parts_cannon import PartsCannonService
from ops_hub.services.parts_request_store import PartsRequestStore


def _build_service() -> tuple[PartsCannonService, NotificationService]:
    notifications = NotificationService()
    service = PartsCannonService(
        adapter=PartsCannonAdapter(base_path=None),
        notifications=notifications,
        request_store=PartsRequestStore(file_path=None),
    )
    return service, notifications


def test_create_parts_request_persists_record() -> None:
    service, notifications = _build_service()

    result = asyncio.run(
        service.create_request(
            PartRequestCreate(
                reference="SR-300",
                description="Need heating element",
                requested_by_user_id=42,
                operator_bluefolder_user_id=13051,
            )
        )
    )

    assert "Parts request `1` created" in result.message
    assert "Status: `requested`" in result.message
    assert len(service.request_store.records) == 1
    assert notifications.records[-1].topic == "parts.request.created"


def test_list_parts_requests_returns_saved_records() -> None:
    service, _ = _build_service()
    asyncio.run(
        service.create_request(
            PartRequestCreate(
                reference="SR-300",
                description="Need heating element",
                requested_by_user_id=42,
            )
        )
    )

    result = asyncio.run(service.list_requests())

    assert "Parts requests" in result.message
    assert "`1` `requested` `SR-300` requested by `42`" in result.message
    assert "Description: Need heating element" in result.message


def test_update_parts_request_changes_status() -> None:
    service, notifications = _build_service()
    asyncio.run(
        service.create_request(
            PartRequestCreate(
                reference="SR-300",
                description="Need heating element",
                requested_by_user_id=42,
            )
        )
    )

    result = asyncio.run(
        service.update_request(
            PartRequestUpdate(
                request_id=1,
                status="ordered",
                updated_by_user_id=99,
            )
        )
    )

    assert "Parts request `1` updated" in result.message
    assert "Status: `ordered`" in result.message
    assert service.request_store.records[0].status == "ordered"
    assert notifications.records[-1].topic == "parts.request.updated"


def test_list_parts_requests_rejects_invalid_status_filter() -> None:
    service, _ = _build_service()

    result = asyncio.run(service.list_requests(status="bad-status"))

    assert "Invalid parts request status." in result.message
    assert "`requested`" in result.message


def test_update_parts_request_rejects_invalid_status() -> None:
    service, _ = _build_service()

    result = asyncio.run(
        service.update_request(
            PartRequestUpdate(
                request_id=1,
                status="bad-status",
                updated_by_user_id=99,
            )
        )
    )

    assert "Invalid parts request status." in result.message


def test_list_parts_requests_can_filter_by_requester() -> None:
    service, _ = _build_service()
    asyncio.run(
        service.create_request(
            PartRequestCreate(
                reference="SR-300",
                description="Need heating element",
                requested_by_user_id=42,
            )
        )
    )
    asyncio.run(
        service.create_request(
            PartRequestCreate(
                reference="SR-301",
                description="Need control board",
                requested_by_user_id=99,
            )
        )
    )

    result = asyncio.run(service.list_requests(requested_by_user_id=42))

    assert "`SR-300`" in result.message
    assert "`SR-301`" not in result.message
