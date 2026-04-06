from __future__ import annotations

import builtins
from pathlib import Path

from ops_hub.services.service_smith import ServiceSmithService
from ops_hub.services.service_smith_bluefolder import (
    BlueFolderImportResult,
    BlueFolderImportPlan,
    BlueFolderPayloadPreview,
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
