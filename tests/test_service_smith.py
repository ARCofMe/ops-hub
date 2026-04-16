from __future__ import annotations

import builtins
from pathlib import Path

from ops_hub.services.service_smith import ServiceSmithService
from ops_hub.services.service_smith_bluefolder import (
    BlueFolderImportResult,
    BlueFolderImportPlan,
    BlueFolderPayloadPreview,
    ServiceSmithBlueFolderClient,
)
from ops_hub.services.service_smith_profile_store import ServiceSmithProfileStore
from types import SimpleNamespace


def test_analyze_spreadsheet_payload_reads_rows_and_flags_issues(tmp_path: Path) -> None:
    spreadsheet = tmp_path / "intake.csv"
    spreadsheet.write_text(
        "\n".join(
            [
                "Customer Name,Email,Phone,Subject,Description,Address,City,State,Zip",
                "Pat Smith,Pat@example.com,2075551212,No heat,,123 Main St,Lewiston,Maine,04240",
                "Chris Jones,bad-email,555,No cool,Unit warm,,Auburn,ME,0421",
            ]
        ),
        encoding="utf-8",
    )

    service = ServiceSmithService(settings=SimpleNamespace())
    payload = service.analyze_spreadsheet_payload(spreadsheet_path=str(spreadsheet))

    assert payload["selectedAdapter"]["name"] == "default"
    assert payload["rowCount"] == 2
    assert payload["previewRows"][0]["customer_email"] == "pat@example.com"
    assert any(issue["message"] == "Missing subject/description" for issue in payload["validationIssues"]) is False
    assert any("State should usually be 2 letters" in issue["message"] for issue in payload["validationIssues"])
    assert any("Questionable email format" in issue["message"] for issue in payload["validationIssues"])


def test_list_formats_payload_includes_default_template() -> None:
    payload = ServiceSmithService(settings=SimpleNamespace()).list_formats_payload()

    assert any(item["name"] == "default" for item in payload["items"])


def test_preview_import_payload_returns_plans(monkeypatch, tmp_path: Path) -> None:
    spreadsheet = tmp_path / "intake.csv"
    spreadsheet.write_text(
        "Customer Name,Subject,Address,City,State,Zip\nPat Smith,No heat,123 Main St,Lewiston,ME,04240\n",
        encoding="utf-8",
    )

    class DummyClient:
        def __init__(self, settings):
            self.settings = settings

        def plan_import(self, row, duplicate_mode="skip"):
            return BlueFolderImportPlan(
                row_number=row.get("source_row_number"),
                customer_action="create_customer",
                location_action="create_location",
                contact_action="create_contact",
                service_request_action="create_service_request",
                notes=[f"duplicate_mode={duplicate_mode}"],
            )

    monkeypatch.setattr("ops_hub.services.service_smith.ServiceSmithBlueFolderClient", DummyClient)
    service = ServiceSmithService(settings=SimpleNamespace())

    payload = service.preview_import_payload(spreadsheet_path=str(spreadsheet), duplicate_mode="allow")

    assert payload["previewMode"] == "plan"
    assert payload["duplicateMode"] == "allow"
    assert payload["items"][0]["service_request_action"] == "create_service_request"


def test_preview_import_payload_supports_payload_preview_mode(monkeypatch, tmp_path: Path) -> None:
    spreadsheet = tmp_path / "intake.csv"
    spreadsheet.write_text(
        "Customer Name,Subject,Address,City,State,Zip\nPat Smith,No heat,123 Main St,Lewiston,ME,04240\n",
        encoding="utf-8",
    )

    class DummyClient:
        def __init__(self, settings):
            self.settings = settings

        def preview_payloads(self, row, duplicate_mode="skip"):
            return BlueFolderPayloadPreview(
                row_number=row.get("source_row_number"),
                customer_payload={"name": row.get("customer_name")},
                location_payload={"address": row.get("address")},
                contact_payload=None,
                service_request_payload={"subject": row.get("subject")},
                notes=[f"duplicate_mode={duplicate_mode}"],
            )

    monkeypatch.setattr("ops_hub.services.service_smith.ServiceSmithBlueFolderClient", DummyClient)
    service = ServiceSmithService(settings=SimpleNamespace())

    payload = service.preview_import_payload(
        spreadsheet_path=str(spreadsheet),
        duplicate_mode="error",
        preview_mode="payload_preview",
    )

    assert payload["previewMode"] == "payload_preview"
    assert payload["items"][0]["customer_payload"]["name"] == "Pat Smith"
    assert payload["items"][0]["service_request_payload"]["subject"] == "No heat"


def test_import_spreadsheet_payload_returns_summary(monkeypatch, tmp_path: Path) -> None:
    spreadsheet = tmp_path / "intake.csv"
    spreadsheet.write_text(
        "Customer Name,Subject,Address,City,State,Zip\nPat Smith,No heat,123 Main St,Lewiston,ME,04240\n",
        encoding="utf-8",
    )

    class DummyClient:
        def __init__(self, settings):
            self.settings = settings

        def ensure_customer_and_import(self, row, duplicate_mode="skip"):
            return BlueFolderImportResult(
                row_number=row.get("source_row_number"),
                customer_id="123",
                customer_location_id="456",
                customer_contact_id="789",
                service_request_id="999",
                status="imported",
                created_customer=True,
                created_location=True,
                created_contact=True,
            )

    monkeypatch.setattr("ops_hub.services.service_smith.ServiceSmithBlueFolderClient", DummyClient)
    service = ServiceSmithService(settings=SimpleNamespace())

    payload = service.import_spreadsheet_payload(spreadsheet_path=str(spreadsheet))

    assert payload["results"][0]["service_request_id"] == "999"
    assert payload["summary"]["status:imported"] == 1
    assert payload["summary"]["created_customer"] == 1


def test_import_spreadsheet_payload_stops_on_fail_fast(monkeypatch, tmp_path: Path) -> None:
    spreadsheet = tmp_path / "intake.csv"
    spreadsheet.write_text(
        "\n".join(
            [
                "Customer Name,Subject,Address,City,State,Zip",
                "Pat Smith,No heat,123 Main St,Lewiston,ME,04240",
                "Chris Jones,No cool,22 Oak St,Auburn,ME,04210",
            ]
        ),
        encoding="utf-8",
    )

    class DummyClient:
        calls = 0

        def __init__(self, settings):
            self.settings = settings

        def ensure_customer_and_import(self, row, duplicate_mode="skip"):
            DummyClient.calls += 1
            if DummyClient.calls == 1:
                return BlueFolderImportResult(
                    row_number=row.get("source_row_number"),
                    customer_id=None,
                    customer_location_id=None,
                    customer_contact_id=None,
                    service_request_id=None,
                    status="duplicate_conflict",
                )
            return BlueFolderImportResult(
                row_number=row.get("source_row_number"),
                customer_id="123",
                customer_location_id="456",
                customer_contact_id="789",
                service_request_id="999",
                status="imported",
            )

    monkeypatch.setattr("ops_hub.services.service_smith.ServiceSmithBlueFolderClient", DummyClient)
    service = ServiceSmithService(settings=SimpleNamespace())

    payload = service.import_spreadsheet_payload(
        spreadsheet_path=str(spreadsheet),
        fail_fast=True,
    )

    assert len(payload["results"]) == 1
    assert payload["results"][0]["status"] == "duplicate_conflict"
    assert payload["summary"]["status:duplicate_conflict"] == 1


def test_preview_manual_service_request_payload_checks_existing_bluefolder_records(monkeypatch) -> None:
    class DummyClient:
        def __init__(self, settings):
            self.settings = settings

        def plan_import(self, row, duplicate_mode="skip"):
            return BlueFolderImportPlan(
                row_number=row.get("source_row_number"),
                customer_action="use_existing",
                location_action="use_existing",
                contact_action="create_contact",
                service_request_action="error_duplicate",
                existing_customer_id="123",
                existing_location_id="456",
                existing_service_request_id="999",
                notes=[f"external_id={row.get('external_id')}", f"duplicate_mode={duplicate_mode}"],
            )

        def preview_payloads(self, row, duplicate_mode="skip"):
            return BlueFolderPayloadPreview(
                row_number=row.get("source_row_number"),
                customer_payload=None,
                location_payload=None,
                contact_payload={"firstName": "Pat"},
                service_request_payload={"subject": row.get("subject"), "externalId": row.get("external_id")},
                existing_customer_id="123",
                existing_location_id="456",
                existing_service_request_id="999",
                notes=[f"duplicate_mode={duplicate_mode}"],
            )

    monkeypatch.setattr("ops_hub.services.service_smith.ServiceSmithBlueFolderClient", DummyClient)
    service = ServiceSmithService(settings=SimpleNamespace())

    payload = service.preview_manual_service_request_payload(
        request={
            "customerName": "Pat Smith",
            "customerPhone": "2075551212",
            "address": "123 Main St",
            "city": "Lewiston",
            "state": "me",
            "postalCode": "04240",
            "requestedWindow": "8 AM - 10 AM",
            "subject": "No heat",
            "externalId": "phone-100",
        },
        duplicate_mode="error",
    )

    assert payload["blockingIssueCount"] == 0
    assert payload["row"]["customer_phone"] == "207-555-1212"
    assert payload["row"]["state"] == "ME"
    assert payload["row"]["service_window"] == "8 AM - 10 AM"
    assert payload["plan"]["existing_service_request_id"] == "999"
    assert payload["plan"]["service_request_action"] == "error_duplicate"


def test_import_manual_service_request_requires_confirmation(monkeypatch) -> None:
    class DummyClient:
        def __init__(self, settings):
            self.settings = settings

    monkeypatch.setattr("ops_hub.services.service_smith.ServiceSmithBlueFolderClient", DummyClient)
    service = ServiceSmithService(settings=SimpleNamespace())

    try:
        service.import_manual_service_request_payload(
            request={"customerName": "Pat Smith", "subject": "No heat"},
            confirmed=False,
        )
    except ValueError as exc:
        assert "preview confirmation" in str(exc)
    else:
        raise AssertionError("Expected manual import to require confirmation.")


def test_import_manual_service_request_returns_result(monkeypatch) -> None:
    class DummyClient:
        def __init__(self, settings):
            self.settings = settings

        def ensure_customer_and_import(self, row, duplicate_mode="skip"):
            return BlueFolderImportResult(
                row_number=row.get("source_row_number"),
                customer_id="123",
                customer_location_id="456",
                customer_contact_id="789",
                service_request_id="999",
                status="imported",
                created_customer=False,
                created_location=True,
                created_contact=True,
                notes=[f"duplicate_mode={duplicate_mode}"],
            )

    monkeypatch.setattr("ops_hub.services.service_smith.ServiceSmithBlueFolderClient", DummyClient)
    service = ServiceSmithService(settings=SimpleNamespace())

    payload = service.import_manual_service_request_payload(
        request={"customerName": "Pat Smith", "address": "123 Main St", "subject": "No heat"},
        duplicate_mode="error",
        confirmed=True,
    )

    assert payload["success"] is True
    assert payload["result"]["service_request_id"] == "999"
    assert payload["row"]["external_id"].startswith("routedesk-manual-")
    assert payload["summary"]["created_location"] == 1


def test_manual_service_request_rejects_invalid_duplicate_mode(monkeypatch) -> None:
    class DummyClient:
        def __init__(self, settings):
            self.settings = settings

    monkeypatch.setattr("ops_hub.services.service_smith.ServiceSmithBlueFolderClient", DummyClient)
    service = ServiceSmithService(settings=SimpleNamespace())

    try:
        service.preview_manual_service_request_payload(
            request={"customerName": "Pat Smith", "subject": "No heat"},
            duplicate_mode="maybe",
        )
    except ValueError as exc:
        assert "duplicate_mode" in str(exc)
    else:
        raise AssertionError("Expected invalid duplicate mode to fail.")


def test_bluefolder_payload_includes_requested_service_window() -> None:
    client = object.__new__(ServiceSmithBlueFolderClient)
    client.settings = SimpleNamespace(
        service_smith_default_sr_priority="Normal",
        service_smith_default_sr_status="New",
    )

    payload = client.build_service_request_payload(
        {
            "subject": "No heat",
            "description": "Customer has no heat.",
            "service_window": "8 AM - 10 AM",
        },
        customer_id="1",
        customer_location_id="2",
        customer_contact_id="3",
    )

    assert payload["description"] == "Customer has no heat.\nRequested service window: 8 AM - 10 AM"


def test_save_and_delete_profile_payload_round_trip(tmp_path: Path) -> None:
    service = ServiceSmithService(
        settings=SimpleNamespace(),
        profile_store=ServiceSmithProfileStore(file_path=tmp_path / "profiles.json"),
    )

    saved = service.save_profile_payload(
        name="vendor-a",
        format_name="vendor_a",
        field_map_path="/tmp/map.json",
        row_start=2,
        limit=50,
        actor_user_id=123,
    )

    assert saved["profile"]["name"] == "vendor-a"
    assert saved["profile"]["updatedByUserId"] == 123
    assert service.list_profiles_payload()["items"][0]["formatName"] == "vendor_a"

    deleted = service.delete_profile_payload(name="vendor-a")

    assert deleted["name"] == "vendor-a"
    assert service.list_profiles_payload()["items"] == []


def test_analyze_spreadsheet_payload_reports_missing_openpyxl_for_excel(monkeypatch, tmp_path: Path) -> None:
    spreadsheet = tmp_path / "intake.xlsx"
    spreadsheet.write_bytes(b"not-a-real-workbook")

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "openpyxl":
            raise ImportError("missing optional dependency")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    service = ServiceSmithService(settings=SimpleNamespace())

    try:
        service.analyze_spreadsheet_payload(spreadsheet_path=str(spreadsheet))
    except RuntimeError as exc:
        assert "openpyxl is required to import Excel workbooks." in str(exc)
    else:
        raise AssertionError("Expected RuntimeError for missing openpyxl.")
