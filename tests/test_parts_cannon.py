"""Parts Cannon wrapper tests for Ops Hub."""

import asyncio
import json
from pathlib import Path

from ops_hub.integrations.parts_cannon_adapter import PartsCannonAdapter
from ops_hub.models.requests import PartLookupRequest, PartRequestCreate
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


def test_parts_adapter_exports_requests_to_handoff_file(tmp_path: Path) -> None:
    adapter = PartsCannonAdapter(base_path=str(tmp_path))
    service = PartsCannonService(
        adapter=adapter,
        notifications=NotificationService(),
        request_store=PartsRequestStore(file_path=None),
    )
    asyncio.run(
        service.create_request(
            PartRequestCreate(
                reference="SR-200",
                description="Need control board",
                requested_by_user_id=1,
            )
        )
    )

    result = asyncio.run(service.sync_requests_to_parts_system())

    export_path = tmp_path / "ops_hub_exports" / "parts_requests.json"
    assert "Status: `exported`" in result.message
    assert f"Export path: `{export_path}`" in result.message
    payload = json.loads(export_path.read_text(encoding="utf-8"))
    assert payload[0]["reference"] == "SR-200"


def test_parts_adapter_sync_reports_unconfigured_status() -> None:
    service = PartsCannonService(
        adapter=PartsCannonAdapter(base_path=None),
        notifications=NotificationService(),
        request_store=PartsRequestStore(file_path=None),
    )

    result = asyncio.run(service.sync_requests_to_parts_system())

    assert "Status: `unconfigured`" in result.message
