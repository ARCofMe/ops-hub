"""Parts Cannon wrapper tests for Ops Hub."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from ops_hub.integrations.parts_cannon_adapter import PartsCannonAdapter
from ops_hub.models.requests import PartLookupRequest, PartRequestCreate, PartRequestUpdate
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

    assert result.integration_status == "handoff_ready"
    assert result.available is True
    assert result.source_path == tmp_path
    assert result.export_file_exists is False
    assert result.receipt_file_exists is False


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

    assert "**Part Lookup SR-200**" in result.message
    assert "**Parts System**" in result.message
    assert "Status: `handoff_ready`" in result.message
    assert "Details: Parts handoff directory is available for request export and receipt import." in result.message
    assert "**Tracked Requests**" in result.message
    assert "No tracked parts requests found for this reference." in result.message
    assert "**Context**" in result.message
    assert "Notifications: `dry_run`" in result.message
    assert len(notifications.records) == 1
    assert notifications.records[0].topic == "parts.lookup"


def test_parts_service_lookup_includes_matching_tracked_requests(tmp_path: Path) -> None:
    notifications = NotificationService()
    service = PartsCannonService(
        adapter=PartsCannonAdapter(base_path=str(tmp_path)),
        notifications=notifications,
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
    asyncio.run(
        service.update_request(
            PartRequestUpdate(
                request_id=1,
                status="ordered",
                updated_by_user_id=1,
            )
        )
    )

    result = asyncio.run(service.lookup_part(PartLookupRequest(reference="SR-200", requested_by_user_id=1)))

    assert "Tracked requests: `1`" in result.message
    assert "Open requests: `1`" in result.message
    assert "`1` `ordered` requested by <@1>" in result.message
    assert "Description: Need control board" in result.message


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
    asyncio.run(
        service.create_request(
            PartRequestCreate(
                reference="SR-201",
                description="Already resolved",
                requested_by_user_id=1,
            )
        )
    )
    asyncio.run(
        service.update_request(
            PartRequestUpdate(
                request_id=2,
                status="resolved",
                updated_by_user_id=1,
            )
        )
    )

    result = asyncio.run(service.sync_requests_to_parts_system())

    export_path = tmp_path / "ops_hub_exports" / "parts_requests.json"
    assert "Status: `exported`" in result.message
    assert f"Export path: `{export_path}`" in result.message
    assert "Synced at: `" in result.message
    payload = json.loads(export_path.read_text(encoding="utf-8"))
    assert len(payload) == 1
    assert payload[0]["reference"] == "SR-200"
    assert service.request_store.records[0].last_synced_at is not None
    assert service.request_store.records[1].last_synced_at is None


def test_parts_adapter_sync_reports_unconfigured_status() -> None:
    service = PartsCannonService(
        adapter=PartsCannonAdapter(base_path=None),
        notifications=NotificationService(),
        request_store=PartsRequestStore(file_path=None),
    )

    result = asyncio.run(service.sync_requests_to_parts_system())

    assert "Status: `unconfigured`" in result.message


def test_parts_adapter_reconciles_receipts_from_handoff_directory(tmp_path: Path) -> None:
    export_dir = tmp_path / "ops_hub_exports"
    export_dir.mkdir()
    (export_dir / "parts_request_receipts.json").write_text(
        json.dumps(
            [
                {"request_id": 1, "status": "ordered", "note": "PO created"},
                {"request_id": 999, "status": "received", "note": "unknown request"},
                {"request_id": 1, "status": "not-a-real-status", "note": "bad status"},
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    service = PartsCannonService(
        adapter=PartsCannonAdapter(base_path=str(tmp_path)),
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

    result = asyncio.run(service.reconcile_requests_from_parts_system())

    assert "Status: `imported`" in result.message
    assert "Applied receipts: `1`" in result.message
    assert "Ignored receipts: `2`" in result.message
    assert service.request_store.records[0].status == "ordered"
    assert service.request_store.records[0].downstream_note == "PO created"
    assert service.request_store.records[0].last_reconciled_at is not None


def test_parts_adapter_reconcile_reports_missing_receipt_file(tmp_path: Path) -> None:
    service = PartsCannonService(
        adapter=PartsCannonAdapter(base_path=str(tmp_path)),
        notifications=NotificationService(),
        request_store=PartsRequestStore(file_path=None),
    )

    result = asyncio.run(service.reconcile_requests_from_parts_system())

    assert "Status: `no_receipts`" in result.message


def test_parts_cannon_builds_recommendation_conversation_from_evidence() -> None:
    service = PartsCannonService(
        adapter=PartsCannonAdapter(base_path=None),
        notifications=NotificationService(),
        request_store=PartsRequestStore(file_path=None),
        complaint_intelligence_service=SimpleNamespace(
            get_service_request_payload=lambda **_: asyncio.sleep(
                0,
                result={
                    "available": True,
                    "integrationStatus": "ok",
                    "evidencePacket": {
                        "version": "evidence.v1",
                        "classification": {"matchedHistoricalRequestCount": 2, "complaintTags": ["no_cool"]},
                        "confidence": "moderate",
                        "rankedParts": [
                            {
                                "item": "FAN-1",
                                "itemType": "part",
                                "score": 0.75,
                                "matchingRequestCount": 2,
                            }
                        ],
                        "diagnosticQuestions": ["Is the evaporator fan running?"],
                        "useConstraints": ["Use rankedParts as historical evidence, not a guaranteed diagnosis."],
                    },
                },
            )
        ),
    )

    payload = asyncio.run(service.get_recommendation_conversation_payload(sr_id=1001))

    assert payload["available"] is True
    assert payload["conversation"]["supportedPartRecommendations"][0]["item"] == "FAN-1"
    assert payload["conversation"]["diagnosticQuestions"] == ["Is the evaporator fan running?"]
    assert "Do not add unsupported parts" in payload["conversation"]["suggestedReply"]
    assert "FAN-1" in payload["conversation"]["suggestedReply"]


def test_parts_cases_include_tenant_active_parts_statuses_without_tracked_requests(tmp_path: Path) -> None:
    (tmp_path / "bluefolder_status_inventory.json").write_text(
        json.dumps(
            {
                "service_request": {
                    "tenant_ui_status_options": ["NEED PARTS/SCHEDULE", "Completed"],
                }
            }
        ),
        encoding="utf-8",
    )
    service = PartsCannonService(
        adapter=PartsCannonAdapter(base_path=str(tmp_path)),
        notifications=NotificationService(),
        request_store=PartsRequestStore(file_path=None),
        workflow_state_service=SimpleNamespace(
            bluefolder_service=SimpleNamespace(
                adapter=SimpleNamespace(base_path=str(tmp_path)),
                get_service_requests_for_statuses=lambda statuses: asyncio.sleep(
                    0,
                    result=[{"id": "100", "status": "NEED PARTS/SCHEDULE"}] if "NEED PARTS/SCHEDULE" in statuses else [],
                ),
                get_parts_snapshot=lambda sr_id: asyncio.sleep(0, result=None),
                get_job_summary=lambda reference, include_customer_contacts=False: asyncio.sleep(
                    0,
                    result=SimpleNamespace(service_request_status="NEED PARTS/SCHEDULE"),
                ),
            ),
            get_parts_case=lambda reference: asyncio.sleep(
                0,
                result=SimpleNamespace(
                    case_id=reference,
                    reference=reference,
                    sr_id=100,
                    stage="no_recent_parts_context",
                    stage_label="No Recent Parts Context",
                    status="open",
                    open_request_ids=[],
                    assigned_parts_user_id=None,
                    requested_by_user_id=None,
                    technician_bluefolder_user_id=None,
                    service_request_status="NEED PARTS/SCHEDULE",
                    latest_status_text=None,
                    latest_issue_text=None,
                    blocker=None,
                    next_action="Review parts status.",
                    updated_at=None,
                    age_hours=None,
                    age_bucket=None,
                ),
            ),
            refresh_dispatch_attention=lambda mappings: asyncio.sleep(0, result=(0, [])),
            current_snapshot=lambda: SimpleNamespace(parts_cases=[]),
        ),
    )

    payload = asyncio.run(service.get_parts_cases_payload(status="open"))

    assert [item["reference"] for item in payload["items"]] == ["SR-100"]
    assert payload["items"][0]["serviceRequestStatus"] == "NEED PARTS/SCHEDULE"
