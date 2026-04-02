from __future__ import annotations

from pathlib import Path

from ops_hub.services.service_smith import ServiceSmithService


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

    service = ServiceSmithService()
    payload = service.analyze_spreadsheet_payload(spreadsheet_path=str(spreadsheet))

    assert payload["selectedAdapter"]["name"] == "default"
    assert payload["rowCount"] == 2
    assert payload["previewRows"][0]["customer_email"] == "pat@example.com"
    assert any(issue["message"] == "Missing subject/description" for issue in payload["validationIssues"]) is False
    assert any("State should usually be 2 letters" in issue["message"] for issue in payload["validationIssues"])
    assert any("Questionable email format" in issue["message"] for issue in payload["validationIssues"])


def test_list_formats_payload_includes_default_template() -> None:
    payload = ServiceSmithService().list_formats_payload()

    assert any(item["name"] == "default" for item in payload["items"])
