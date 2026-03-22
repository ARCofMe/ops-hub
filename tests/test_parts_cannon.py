"""Parts Cannon wrapper tests for Ops Hub."""

import asyncio
from pathlib import Path

from ops_hub.integrations.parts_cannon_adapter import PartsCannonAdapter
from ops_hub.models.requests import PartLookupRequest
from ops_hub.services.notifications import NotificationService
from ops_hub.services.parts_cannon import PartsCannonService
from ops_hub.services.parts_request_store import PartsRequestStore


def test_parts_adapter_reports_unconfigured_status() -> None:
    adapter = PartsCannonAdapter(base_path=None)

    result = asyncio.run(adapter.get_part_status("SR-200"))

    assert result.integration_status == "unconfigured"
    assert result.available is False


def test_parts_adapter_reports_ready_status_for_existing_path(tmp_path: Path) -> None:
    adapter = PartsCannonAdapter(base_path=str(tmp_path))

    result = asyncio.run(adapter.get_part_status("SR-200"))

    assert result.integration_status == "placeholder_ready"
    assert result.available is True
    assert result.source_path == tmp_path


def test_parts_service_includes_wrapper_status_in_message(tmp_path: Path) -> None:
    notifications = NotificationService()
    service = PartsCannonService(
        adapter=PartsCannonAdapter(base_path=str(tmp_path)),
        notifications=notifications,
        request_store=PartsRequestStore(file_path=None),
    )

    result = asyncio.run(
        service.lookup_part(PartLookupRequest(reference="SR-200", requested_by_user_id=1))
    )

    assert "Part `SR-200`" in result.message
    assert "Parts Cannon: `placeholder_ready`" in result.message
    assert "Details: Parts workflow wrapper path is available. Wrapper behavior is not implemented yet." in result.message
    assert "Notifications: `dry_run`" in result.message
    assert len(notifications.records) == 1
    assert notifications.records[0].topic == "parts.lookup"
