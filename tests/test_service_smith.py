from __future__ import annotations

from pathlib import Path

from ops_hub.services.service_smith import ServiceSmithService
from ops_hub.services.service_smith_bluefolder import (
    BlueFolderImportResult,
    BlueFolderImportPlan,
    BlueFolderPayloadPreview,
)
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
