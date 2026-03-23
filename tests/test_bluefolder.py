"""BlueFolder adapter and service tests for Ops Hub."""

import asyncio
from pathlib import Path
import textwrap

from ops_hub.integrations.bluefolder_adapter import BlueFolderAdapter
from ops_hub.integrations.dispatch_adapter import DispatchAdapter
from ops_hub.models.requests import JobLookupRequest, TechnicianMappingRecord
from ops_hub.services.bluefolder import BlueFolderService
from ops_hub.services.dispatch import DispatchService


class DummyDispatchAdapter(DispatchAdapter):
    """Dispatch adapter test double."""

    async def get_job(self, reference: str, bluefolder_summary=None, technician_bluefolder_user_id=None):
        return await super().get_job(reference, bluefolder_summary, technician_bluefolder_user_id)


def test_bluefolder_adapter_reports_unconfigured_status() -> None:
    adapter = BlueFolderAdapter(base_path=None)

    result = asyncio.run(adapter.get_job_summary("SR-100"))

    assert result.integration_status == "unconfigured"
    assert result.available is False


def test_bluefolder_adapter_reports_import_error_for_non_library_path(tmp_path: Path) -> None:
    adapter = BlueFolderAdapter(base_path=str(tmp_path))

    result = asyncio.run(adapter.get_job_summary("SR-100"))

    assert result.integration_status == "import_error"
    assert result.available is False
    assert result.source_path == tmp_path


def test_dispatch_service_includes_bluefolder_status_in_message(tmp_path: Path) -> None:
    bluefolder_service = BlueFolderService(adapter=BlueFolderAdapter(base_path=str(tmp_path)))
    service = DispatchService(
        adapter=DummyDispatchAdapter(base_path=None),
        bluefolder_service=bluefolder_service,
    )

    result = asyncio.run(
        service.lookup_job(JobLookupRequest(reference="SR-100", requested_by_user_id=1))
    )

    assert "**Job SR-100**" in result.message
    assert "**BlueFolder**" in result.message
    assert "Status: `import_error`" in result.message
    assert "Failed to import bluefolder_api from configured path" in result.message
    assert "**Dispatch**" in result.message
    assert "Status: `unconfigured`" in result.message


def test_dispatch_service_lists_current_assignments_for_mapped_user(tmp_path: Path) -> None:
    dispatch_package = tmp_path / "optimized_routing"
    dispatch_package.mkdir()
    (dispatch_package / "__init__.py").write_text("", encoding="utf-8")
    (dispatch_package / "bluefolder_integration.py").write_text(
        textwrap.dedent(
            """
            class BlueFolderIntegration:
                def get_user_assignments_today(self, user_id: int):
                    return [
                        {
                            "serviceRequestId": "100",
                            "subject": "Dryer repair",
                            "city": "Portland",
                            "state": "ME",
                            "routeLabel": "AM",
                            "start": "08:00",
                        },
                        {
                            "serviceRequestId": "101",
                            "subject": "Washer repair",
                            "city": "Lewiston",
                            "state": "ME",
                            "routeLabel": "PM",
                        },
                    ]

                def get_user_origin_address(self, user_id: int):
                    return "South Paris, ME"
            """
        ),
        encoding="utf-8",
    )
    service = DispatchService(
        adapter=DummyDispatchAdapter(base_path=str(tmp_path)),
        bluefolder_service=BlueFolderService(adapter=BlueFolderAdapter(base_path=None)),
    )

    result = asyncio.run(
        service.lookup_job(
            JobLookupRequest(
                reference=None,
                requested_by_user_id=1,
                technician_bluefolder_user_id=13051,
            )
        )
    )

    assert "Current assignments for BlueFolder user `13051`" in result.message
    assert "Assignment count: `2`" in result.message
    assert "Origin: South Paris, ME" in result.message
    assert "`SR-100` Dryer repair [Portland ME | AM | start 08:00]" in result.message
    assert "`SR-101` Washer repair [Lewiston ME | PM]" in result.message


def test_dispatch_service_reports_origin_when_no_assignments_exist(tmp_path: Path) -> None:
    dispatch_package = tmp_path / "optimized_routing"
    dispatch_package.mkdir()
    (dispatch_package / "__init__.py").write_text("", encoding="utf-8")
    (dispatch_package / "bluefolder_integration.py").write_text(
        textwrap.dedent(
            """
            class BlueFolderIntegration:
                def get_user_assignments_today(self, user_id: int):
                    return []

                def get_user_origin_address(self, user_id: int):
                    return "South Paris, ME"
            """
        ),
        encoding="utf-8",
    )
    service = DispatchService(
        adapter=DummyDispatchAdapter(base_path=str(tmp_path)),
        bluefolder_service=BlueFolderService(adapter=BlueFolderAdapter(base_path=None)),
    )

    result = asyncio.run(
        service.lookup_job(
            JobLookupRequest(
                reference=None,
                requested_by_user_id=1,
                technician_bluefolder_user_id=13051,
            )
        )
    )

    assert "No current assignments were found for BlueFolder user `13051`." in result.message
    assert "Origin: South Paris, ME" in result.message


def test_dispatch_service_uses_bluefolder_name_for_unmapped_user(tmp_path: Path) -> None:
    dispatch_package = tmp_path / "optimized_routing"
    dispatch_package.mkdir()
    (dispatch_package / "__init__.py").write_text("", encoding="utf-8")
    (dispatch_package / "bluefolder_integration.py").write_text(
        textwrap.dedent(
            """
            class BlueFolderIntegration:
                def get_user_assignments_today(self, user_id: int):
                    return []

                def get_user_origin_address(self, user_id: int):
                    return "South Paris, ME"
            """
        ),
        encoding="utf-8",
    )
    bluefolder_package = tmp_path / "bluefolder_api"
    bluefolder_package.mkdir()
    (bluefolder_package / "__init__.py").write_text("", encoding="utf-8")
    (bluefolder_package / "client.py").write_text(
        textwrap.dedent(
            """
            class _Users:
                def list_active(self):
                    return [
                        {"id": "13051", "firstName": "Mike", "lastName": "Smith", "inactive": False},
                    ]

            class BlueFolderClient:
                def __init__(self, base_url: str | None = None):
                    self.base_url = base_url
                    self.users = _Users()
            """
        ),
        encoding="utf-8",
    )
    service = DispatchService(
        adapter=DummyDispatchAdapter(base_path=str(tmp_path)),
        bluefolder_service=BlueFolderService(
            adapter=BlueFolderAdapter(
                base_path=str(tmp_path),
                api_key="key",
                account_name="acme",
            )
        ),
    )

    result = asyncio.run(
        service.lookup_job(
            JobLookupRequest(
                reference=None,
                requested_by_user_id=1,
                technician_bluefolder_user_id=13051,
            )
        )
    )

    assert "No current assignments were found for Mike Smith." in result.message


def test_bluefolder_adapter_marks_user_directory_unavailable_after_failure(tmp_path: Path) -> None:
    bluefolder_package = tmp_path / "bluefolder_api"
    bluefolder_package.mkdir()
    (bluefolder_package / "__init__.py").write_text("", encoding="utf-8")
    (bluefolder_package / "client.py").write_text(
        textwrap.dedent(
            """
            class _Users:
                def list_active(self):
                    raise RuntimeError("Invalid XML response")

            class BlueFolderClient:
                def __init__(self, base_url: str | None = None):
                    self.base_url = base_url
                    self.users = _Users()
            """
        ),
        encoding="utf-8",
    )
    adapter = BlueFolderAdapter(
        base_path=str(tmp_path),
        api_key="key",
        account_name="acme",
    )

    first = asyncio.run(adapter.get_active_user_directory())
    second = asyncio.run(adapter.get_active_user_directory())
    user_name = asyncio.run(adapter.get_user_name(13051))

    assert first == {}
    assert second == {}
    assert user_name is None
    assert adapter._active_user_directory_unavailable is True


def test_dispatch_service_builds_dispatch_board_summary(tmp_path: Path) -> None:
    dispatch_package = tmp_path / "optimized_routing"
    dispatch_package.mkdir()
    (dispatch_package / "__init__.py").write_text("", encoding="utf-8")
    (dispatch_package / "bluefolder_integration.py").write_text(
        textwrap.dedent(
            """
            class BlueFolderIntegration:
                def get_user_assignments_today(self, user_id: int):
                    if user_id == 13051:
                        return [{"serviceRequestId": "100", "subject": "Dryer repair"}]
                    return []

                def get_user_origin_address(self, user_id: int):
                    if user_id == 13051:
                        return "South Paris, ME"
                    return "Lewiston, ME"
            """
        ),
        encoding="utf-8",
    )
    service = DispatchService(
        adapter=DummyDispatchAdapter(base_path=str(tmp_path)),
        bluefolder_service=BlueFolderService(adapter=BlueFolderAdapter(base_path=None)),
    )

    result = asyncio.run(
        service.lookup_dispatch_board(
            [
                TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051),
                TechnicianMappingRecord(discord_user_id=43, bluefolder_user_id=13052),
            ]
        )
    )

    assert "**Dispatch Board**" in result.message
    assert "Mapped techs: `2`" in result.message
    assert "Active techs: `1`" in result.message
    assert "Total visible assignments: `1`" in result.message
    assert "Technician: <@42> | `1` assignment(s)" in result.message
    assert "Next job: `SR-100` Dryer repair" in result.message
    assert "Technician: <@43> | `0` assignment(s)" in result.message


def test_dispatch_service_builds_dispatch_attention_summary(tmp_path: Path) -> None:
    dispatch_package = tmp_path / "optimized_routing"
    dispatch_package.mkdir()
    (dispatch_package / "__init__.py").write_text("", encoding="utf-8")
    (dispatch_package / "bluefolder_integration.py").write_text(
        textwrap.dedent(
            """
            class BlueFolderIntegration:
                def get_user_assignments_today(self, user_id: int):
                    if user_id == 13051:
                        return [
                            {"serviceRequestId": "100", "subject": "Dryer repair", "city": "Portland", "state": "ME", "routeLabel": "AM"},
                            {"serviceRequestId": "101", "subject": "Washer repair", "city": "Lewiston", "state": "ME", "routeLabel": "PM"},
                        ]
                    return []

                def get_user_origin_address(self, user_id: int):
                    return "South Paris, ME"
            """
        ),
        encoding="utf-8",
    )
    bluefolder_package = tmp_path / "bluefolder_api"
    bluefolder_package.mkdir()
    (bluefolder_package / "__init__.py").write_text("", encoding="utf-8")
    (bluefolder_package / "client.py").write_text(
        textwrap.dedent(
            """
            class _Comments:
                def list_for_service_request(self, service_request_id: int):
                    if service_request_id == 100:
                        return [
                            {"author": "Parts", "dateCreated": "2026-03-22 10:00", "text": "Part ready for scheduling at 10:00 AM. Details: all parts are in.", "isVisibleToCustomer": False},
                        ]
                    return [
                        {"author": "Parts", "dateCreated": "2026-03-22 09:00", "text": "Part tracking update: UPS 123", "isVisibleToCustomer": False},
                    ]

            class BlueFolderClient:
                def __init__(self, base_url: str | None = None):
                    self.base_url = base_url
                    self.comments = _Comments()
            """
        ),
        encoding="utf-8",
    )
    service = DispatchService(
        adapter=DummyDispatchAdapter(base_path=str(tmp_path)),
        bluefolder_service=BlueFolderService(
            adapter=BlueFolderAdapter(
                base_path=str(tmp_path),
                api_key="key",
                account_name="acme",
            )
        ),
    )

    result = asyncio.run(
        service.lookup_dispatch_attention(
            [
                TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051),
            ]
        )
    )

    assert "**Dispatch Attention**" in result.message
    assert "Scanned jobs: `2`" in result.message
    assert "Attention jobs: `1`" in result.message
    assert "Actionable stages: `Issue Reported`, `Received`, `Ready for Scheduling`" in result.message
    assert "1. `SR-100` Dryer repair" in result.message
    assert "Stage: `Ready for Scheduling`" in result.message
    assert "Technician: <@42>" in result.message
    assert "Location: Portland ME" in result.message
    assert "Window: `AM`" in result.message
    assert "`SR-101`" not in result.message


def test_dispatch_service_filters_dispatch_attention_by_stage_and_technician(tmp_path: Path) -> None:
    dispatch_package = tmp_path / "optimized_routing"
    dispatch_package.mkdir()
    (dispatch_package / "__init__.py").write_text("", encoding="utf-8")
    (dispatch_package / "bluefolder_integration.py").write_text(
        textwrap.dedent(
            """
            class BlueFolderIntegration:
                def get_user_assignments_today(self, user_id: int):
                    if user_id == 13051:
                        return [{"serviceRequestId": "100", "subject": "Dryer repair"}]
                    if user_id == 13052:
                        return [{"serviceRequestId": "200", "subject": "Washer repair"}]
                    return []

                def get_user_origin_address(self, user_id: int):
                    return "South Paris, ME"
            """
        ),
        encoding="utf-8",
    )
    bluefolder_package = tmp_path / "bluefolder_api"
    bluefolder_package.mkdir()
    (bluefolder_package / "__init__.py").write_text("", encoding="utf-8")
    (bluefolder_package / "client.py").write_text(
        textwrap.dedent(
            """
            class _Comments:
                def list_for_service_request(self, service_request_id: int):
                    if service_request_id == 100:
                        return [{"author": "Parts", "dateCreated": "2026-03-22 10:00", "text": "Part ready for scheduling at 10:00 AM. Details: all parts are in.", "isVisibleToCustomer": False}]
                    return [{"author": "Parts", "dateCreated": "2026-03-22 09:00", "text": "Part received at 9:00 AM. Details: received at shop.", "isVisibleToCustomer": False}]

            class BlueFolderClient:
                def __init__(self, base_url: str | None = None):
                    self.base_url = base_url
                    self.comments = _Comments()
            """
        ),
        encoding="utf-8",
    )
    service = DispatchService(
        adapter=DummyDispatchAdapter(base_path=str(tmp_path)),
        bluefolder_service=BlueFolderService(
            adapter=BlueFolderAdapter(
                base_path=str(tmp_path),
                api_key="key",
                account_name="acme",
            )
        ),
    )

    result = asyncio.run(
        service.lookup_dispatch_attention(
            [
                TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051),
                TechnicianMappingRecord(discord_user_id=43, bluefolder_user_id=13052),
            ],
            stage_filter="part_ready",
            technician_bluefolder_user_id=13051,
        )
    )

    assert "Stage filter: `Ready for Scheduling`" in result.message
    assert "Technician filter: BlueFolder user `13051`" in result.message
    assert "`SR-100` Dryer repair" in result.message
    assert "`SR-200`" not in result.message


def test_dispatch_service_formats_live_bluefolder_summary(tmp_path: Path) -> None:
    bluefolder_package = tmp_path / "bluefolder_api"
    bluefolder_package.mkdir()
    (bluefolder_package / "__init__.py").write_text("", encoding="utf-8")
    (bluefolder_package / "client.py").write_text(
        textwrap.dedent(
            """
            import xml.etree.ElementTree as ET

            class _ServiceRequests:
                def get_by_id(self, service_request_id: int):
                    root = ET.Element("response")
                    sr = ET.SubElement(root, "serviceRequest")
                    ET.SubElement(sr, "customerId").text = "42"
                    ET.SubElement(sr, "customerLocationId").text = "9"
                    ET.SubElement(sr, "description").text = f"SR description {service_request_id}"
                    return root


            class _Customers:
                def get_location_by_id(self, customer_id: str, location_id: str):
                    root = ET.Element("response")
                    location = ET.SubElement(root, "customerLocation")
                    ET.SubElement(location, "addressStreet").text = "123 Main St"
                    ET.SubElement(location, "addressCity").text = "Portland"
                    ET.SubElement(location, "addressState").text = "ME"
                    ET.SubElement(location, "addressPostalCode").text = "04101"
                    return root


            class _Comments:
                def list_for_service_request(self, service_request_id: int):
                    return [
                        {"author": "Parts", "dateCreated": "2026-03-22 10:00", "text": "Part tracking update: UPS 123", "isVisibleToCustomer": False},
                    ]


            class BlueFolderClient:
                def __init__(self, base_url: str | None = None):
                    self.base_url = base_url
                    self.service_requests = _ServiceRequests()
                    self.customers = _Customers()
                    self.comments = _Comments()
            """
        ),
        encoding="utf-8",
    )
    dispatch_package = tmp_path / "optimized_routing"
    dispatch_package.mkdir()
    (dispatch_package / "__init__.py").write_text("", encoding="utf-8")
    (dispatch_package / "routing.py").write_text(
        textwrap.dedent(
            """
            class _Window:
                def __init__(self, name: str):
                    self.name = name


            class _Stop:
                def __init__(self, label: str, address: str):
                    self.label = label
                    self.address = address
                    self.window = _Window("ALL_DAY")


            def bluefolder_to_routestops(assignments):
                assignment = assignments[0]
                address = f"{assignment.get('address')}, {assignment.get('city')}, {assignment.get('state')} {assignment.get('zip')}"
                return [_Stop(f"SR-{assignment.get('serviceRequestId')}", address)]
            """
        ),
        encoding="utf-8",
    )
    (dispatch_package / "bluefolder_integration.py").write_text(
        textwrap.dedent(
            """
            class BlueFolderIntegration:
                def get_user_assignments_today(self, user_id: int):
                    return [{"serviceRequestId": "100"}]

                def get_user_origin_address(self, user_id: int):
                    return "South Paris, ME"
            """
        ),
        encoding="utf-8",
    )
    bluefolder_service = BlueFolderService(
        adapter=BlueFolderAdapter(
            base_path=str(tmp_path),
            api_key="key",
            account_name="acme",
        )
    )
    service = DispatchService(
        adapter=DummyDispatchAdapter(base_path=str(tmp_path)),
        bluefolder_service=bluefolder_service,
    )

    result = asyncio.run(
        service.lookup_job(
            JobLookupRequest(
                reference="SR-100",
                requested_by_user_id=1,
                technician_bluefolder_user_id=13051,
            )
        )
    )

    assert "**Job SR-100**" in result.message
    assert "BlueFolder SR: `100`" in result.message
    assert "Subject: SR description 100" in result.message
    assert "Dispatch: `stop_preview`" in result.message
    assert "Customer ID: `42`" in result.message
    assert "Location ID: `9`" in result.message
    assert "Address: 123 Main St, Portland ME 04101" in result.message
    assert "Dispatch stop: `SR-100`" in result.message
    assert "Dispatch window: `ALL_DAY`" in result.message
    assert "Dispatch stop address: 123 Main St, Portland, ME 04101" in result.message
    assert "Technician assignment: `assigned_today`" in result.message
    assert "Technician origin: South Paris, ME" in result.message
    assert "Parts: `Tracking Posted`" in result.message
    assert "Status detail: Part tracking update: UPS 123" in result.message
    assert "Recommended next action: Track shipment progress and prepare dispatch for receipt or scheduling follow-up." in result.message
    assert "Requester: <@1>" in result.message
    assert "Dispatch detail: Dispatch stop preview built from the existing routing wrapper." in result.message


def test_dispatch_adapter_reports_wrapper_ready_for_existing_project(tmp_path: Path) -> None:
    package_dir = tmp_path / "optimized_routing"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "routing.py").write_text(
        "def bluefolder_to_routestops(assignments):\n    return []\n",
        encoding="utf-8",
    )
    adapter = DispatchAdapter(base_path=str(tmp_path))

    result = asyncio.run(adapter.get_job("SR-100"))

    assert result.integration_status == "wrapper_ready"
    assert result.available is True
    assert result.module_name == "optimized_routing.routing"


def test_bluefolder_adapter_returns_live_read_for_local_library(tmp_path: Path) -> None:
    package_dir = tmp_path / "bluefolder_api"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "client.py").write_text(
        textwrap.dedent(
            """
            import xml.etree.ElementTree as ET

            class _ServiceRequests:
                def get_by_id(self, service_request_id: int):
                    root = ET.Element("response")
                    sr = ET.SubElement(root, "serviceRequest")
                    ET.SubElement(sr, "customerId").text = "42"
                    ET.SubElement(sr, "customerLocationId").text = "9"
                    ET.SubElement(sr, "description").text = f"SR description {service_request_id}"
                    return root


            class _Customers:
                def get_location_by_id(self, customer_id: str, location_id: str):
                    root = ET.Element("response")
                    location = ET.SubElement(root, "customerLocation")
                    ET.SubElement(location, "addressStreet").text = "123 Main St"
                    ET.SubElement(location, "addressCity").text = "Portland"
                    ET.SubElement(location, "addressState").text = "ME"
                    ET.SubElement(location, "addressPostalCode").text = "04101"
                    return root


            class BlueFolderClient:
                def __init__(self, base_url: str | None = None):
                    self.base_url = base_url
                    self.service_requests = _ServiceRequests()
                    self.customers = _Customers()
            """
        ),
        encoding="utf-8",
    )
    adapter = BlueFolderAdapter(
        base_path=str(tmp_path),
        api_key="key",
        account_name="acme",
    )

    result = asyncio.run(adapter.get_job_summary("SR-100"))

    assert result.integration_status == "live_read"
    assert result.available is True
    assert result.service_request_id == "100"
    assert result.subject == "SR description 100"
    assert result.customer_id == "42"
    assert result.customer_location_id == "9"
    assert result.address == "123 Main St"
    assert result.city == "Portland"
    assert result.state == "ME"
    assert result.postal_code == "04101"


def test_bluefolder_service_returns_parts_brief_from_comments(tmp_path: Path) -> None:
    package_dir = tmp_path / "bluefolder_api"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "client.py").write_text(
        textwrap.dedent(
            """
            import xml.etree.ElementTree as ET

            class _ServiceRequests:
                def get_by_id(self, service_request_id: int):
                    root = ET.Element("response")
                    sr = ET.SubElement(root, "serviceRequest")
                    ET.SubElement(sr, "customerName").text = "Jane Customer"
                    ET.SubElement(sr, "customerId").text = "42"
                    ET.SubElement(sr, "customerLocationId").text = "9"
                    ET.SubElement(sr, "description").text = f"SR description {service_request_id}"
                    return root


            class _Customers:
                def get_location_by_id(self, customer_id: str, location_id: str):
                    root = ET.Element("response")
                    location = ET.SubElement(root, "customerLocation")
                    ET.SubElement(location, "addressStreet").text = "123 Main St"
                    ET.SubElement(location, "addressCity").text = "Portland"
                    ET.SubElement(location, "addressState").text = "ME"
                    ET.SubElement(location, "addressPostalCode").text = "04101"
                    return root


            class _Comments:
                def list_for_service_request(self, service_request_id: int):
                    return [
                        {"author": "Parts", "dateCreated": "2026-03-22 10:00", "text": "Tracking update: UPS 123", "isVisibleToCustomer": False},
                        {"author": "Tech", "dateCreated": "2026-03-22 09:00", "text": "General note", "isVisibleToCustomer": False},
                    ]


            class BlueFolderClient:
                def __init__(self, base_url: str | None = None):
                    self.base_url = base_url
                    self.service_requests = _ServiceRequests()
                    self.customers = _Customers()
                    self.comments = _Comments()
            """
        ),
        encoding="utf-8",
    )
    service = BlueFolderService(
        adapter=BlueFolderAdapter(
            base_path=str(tmp_path),
            api_key="key",
            account_name="acme",
        )
    )

    result = asyncio.run(service.get_parts_brief(100))

    assert "**Parts Brief SR-100**" in result.message
    assert "SR: `100`" in result.message
    assert "Subject: SR description 100" in result.message
    assert "Customer: Jane Customer" in result.message
    assert "Parts stage: `Tracking Posted`" in result.message
    assert "Latest status note:" in result.message
    assert "Status detail: Tracking update: UPS 123" in result.message


def test_bluefolder_service_returns_issue_stage_when_only_issue_comments_exist(tmp_path: Path) -> None:
    package_dir = tmp_path / "bluefolder_api"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "client.py").write_text(
        textwrap.dedent(
            """
            import xml.etree.ElementTree as ET

            class _ServiceRequests:
                def get_by_id(self, service_request_id: int):
                    root = ET.Element("response")
                    sr = ET.SubElement(root, "serviceRequest")
                    ET.SubElement(sr, "customerName").text = "Jane Customer"
                    ET.SubElement(sr, "description").text = f"SR description {service_request_id}"
                    return root


            class _Comments:
                def list_for_service_request(self, service_request_id: int):
                    return [
                        {"author": "Tech", "dateCreated": "2026-03-22 09:00", "text": "Missing part reported at 9:00 AM. Details: belt.", "isVisibleToCustomer": False},
                    ]


            class BlueFolderClient:
                def __init__(self, base_url: str | None = None):
                    self.base_url = base_url
                    self.service_requests = _ServiceRequests()
                    self.comments = _Comments()
            """
        ),
        encoding="utf-8",
    )
    service = BlueFolderService(
        adapter=BlueFolderAdapter(
            base_path=str(tmp_path),
            api_key="key",
            account_name="acme",
        )
    )

    result = asyncio.run(service.get_parts_brief(100))

    assert "Parts stage: `Issue Reported`" in result.message
    assert "Latest issue: `missing-part`" in result.message
    assert "Issue detail: Missing part reported" in result.message
    assert "Recommended next action: Parts should review the issue note, confirm the part path, and post an ordered or ETA update." in result.message


def test_bluefolder_service_returns_dispatch_next_action(tmp_path: Path) -> None:
    package_dir = tmp_path / "bluefolder_api"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "client.py").write_text(
        textwrap.dedent(
            """
            import xml.etree.ElementTree as ET

            class _ServiceRequests:
                def get_by_id(self, service_request_id: int):
                    root = ET.Element("response")
                    sr = ET.SubElement(root, "serviceRequest")
                    ET.SubElement(sr, "description").text = f"SR description {service_request_id}"
                    return root

            class _Comments:
                def list_for_service_request(self, service_request_id: int):
                    return [
                        {"author": "Parts", "dateCreated": "2026-03-22 10:00", "text": "Part ready for scheduling at 10:00 AM. Details: all parts are in.", "isVisibleToCustomer": False},
                    ]

            class BlueFolderClient:
                def __init__(self, base_url: str | None = None):
                    self.base_url = base_url
                    self.service_requests = _ServiceRequests()
                    self.comments = _Comments()
            """
        ),
        encoding="utf-8",
    )
    service = BlueFolderService(
        adapter=BlueFolderAdapter(
            base_path=str(tmp_path),
            api_key="key",
            account_name="acme",
        )
    )

    result = asyncio.run(service.get_parts_next_action(100))

    assert "Dispatch next `100`" in result.message
    assert "Parts stage: `Ready for Scheduling`" in result.message
    assert "Recommended next action: Dispatch should contact the customer and move the SR toward scheduling." in result.message


def test_bluefolder_service_lists_parts_notes_from_bluefolder_comments(tmp_path: Path) -> None:
    package_dir = tmp_path / "bluefolder_api"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "client.py").write_text(
        textwrap.dedent(
            """
            class _Comments:
                def list_for_service_request(self, service_request_id: int):
                    return [
                        {"author": "Parts", "dateCreated": "2026-03-22 10:00", "text": "Tracking update: UPS 123", "isVisibleToCustomer": False},
                        {"author": "Tech", "dateCreated": "2026-03-22 09:00", "text": "Missing part reported at 9:00 AM. Details: belt.", "isVisibleToCustomer": False},
                        {"author": "Tech", "dateCreated": "2026-03-22 08:00", "text": "Unrelated note", "isVisibleToCustomer": False},
                    ]

            class BlueFolderClient:
                def __init__(self, base_url: str | None = None):
                    self.base_url = base_url
                    self.comments = _Comments()
            """
        ),
        encoding="utf-8",
    )
    service = BlueFolderService(
        adapter=BlueFolderAdapter(
            base_path=str(tmp_path),
            api_key="key",
            account_name="acme",
        )
    )

    result = asyncio.run(service.get_parts_notes(100))

    assert "Parts notes" in result.message
    assert "Tracking update: UPS 123" in result.message
    assert "Missing part reported" in result.message
    assert "Unrelated note" not in result.message


def test_bluefolder_service_logs_parts_issue_comment(tmp_path: Path) -> None:
    package_dir = tmp_path / "bluefolder_api"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "client.py").write_text(
        textwrap.dedent(
            """
            class _Comments:
                def __init__(self):
                    self.calls = []

                def add_to_service_request(self, service_request_id: int, text: str, visible_to_customer: bool = False):
                    self.calls.append((service_request_id, text, visible_to_customer))
                    return {"ok": True}

            _shared_comments = _Comments()

            class BlueFolderClient:
                def __init__(self, base_url: str | None = None):
                    self.base_url = base_url
                    self.comments = _shared_comments
            """
        ),
        encoding="utf-8",
    )
    service = BlueFolderService(
        adapter=BlueFolderAdapter(
            base_path=str(tmp_path),
            api_key="key",
            account_name="acme",
        )
    )

    result = asyncio.run(
        service.log_parts_issue(
            100,
            issue_type="missing_part",
            details="Need control board",
            requested_by_user_id=42,
        )
    )

    assert "Logged missing-part issue for `100`" in result.message
    assert "Need control board" in result.message
    assert "BlueFolder note: Missing part reported" in result.message


def test_bluefolder_service_logs_parts_update_comment(tmp_path: Path) -> None:
    package_dir = tmp_path / "bluefolder_api"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "client.py").write_text(
        textwrap.dedent(
            """
            class _Comments:
                def __init__(self):
                    self.calls = []

                def add_to_service_request(self, service_request_id: int, text: str, visible_to_customer: bool = False):
                    self.calls.append((service_request_id, text, visible_to_customer))
                    return {"ok": True}

            _shared_comments = _Comments()

            class BlueFolderClient:
                def __init__(self, base_url: str | None = None):
                    self.base_url = base_url
                    self.comments = _shared_comments
            """
        ),
        encoding="utf-8",
    )
    service = BlueFolderService(
        adapter=BlueFolderAdapter(
            base_path=str(tmp_path),
            api_key="key",
            account_name="acme",
        )
    )

    result = asyncio.run(
        service.log_parts_update(
            100,
            update_type="part_tracking",
            details="Label created and moving.",
            requested_by_user_id=42,
            metadata={
                "tracking_number": "1Z999",
                "carrier": "UPS",
                "eta": "tomorrow",
            },
        )
    )

    assert "Logged part-tracking update for `100`" in result.message
    assert "Tracking #: 1Z999." in result.message
    assert "Carrier: UPS." in result.message
    assert "ETA: tomorrow." in result.message
    assert "BlueFolder note: Part tracking update" in result.message


def test_bluefolder_adapter_rejects_non_numeric_reference(tmp_path: Path) -> None:
    adapter = BlueFolderAdapter(base_path=str(tmp_path), api_key="key", account_name="acme")

    result = asyncio.run(adapter.get_job_summary("ticket-alpha"))

    assert result.integration_status == "unsupported_reference"
    assert result.available is False
