"""BlueFolder adapter and service tests for Ops Hub."""

import asyncio
from pathlib import Path
import textwrap

from ops_hub.integrations.bluefolder_adapter import BlueFolderAdapter
from ops_hub.integrations.dispatch_adapter import DispatchAdapter
from ops_hub.models.requests import CustomerContactSummary, JobLookupRequest, TechnicianMappingRecord
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
    assert "`SR-100` Dryer repair [Portland ME | AM | start 8:00 AM]" in result.message
    assert "`SR-101` Washer repair [Lewiston ME | PM]" in result.message


def test_dispatch_service_uses_bluefolder_assignments_when_dispatch_path_is_missing(tmp_path: Path) -> None:
    bluefolder_package = tmp_path / "bluefolder_api"
    bluefolder_package.mkdir()
    (bluefolder_package / "__init__.py").write_text("", encoding="utf-8")
    (bluefolder_package / "client.py").write_text(
        textwrap.dedent(
            """
            import xml.etree.ElementTree as ET

            class _Assignments:
                def list_for_user_range(self, user_id, start_date, end_date, date_range_type=None):
                    return [
                        {"serviceRequestId": "100", "start": "2026-03-24T08:00:00"},
                        {"serviceRequestId": "101", "start": "2026-03-24T11:00:00"},
                    ]

            class _ServiceRequests:
                def get_by_id(self, service_request_id: int):
                    root = ET.Element("response")
                    sr = ET.SubElement(root, "serviceRequest")
                    ET.SubElement(sr, "description").text = (
                        "Dryer repair" if service_request_id == 100 else "Washer repair"
                    )
                    return root

            class BlueFolderClient:
                def __init__(self, base_url: str | None = None):
                    self.base_url = base_url
                    self.assignments = _Assignments()
                    self.service_requests = _ServiceRequests()
            """
        ),
        encoding="utf-8",
    )
    service = DispatchService(
        adapter=DummyDispatchAdapter(base_path="/does/not/exist"),
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

    assert "Current assignments for BlueFolder user `13051`" in result.message
    assert "Assignment count: `2`" in result.message
    assert "`SR-100` Dryer repair [start 8:00 AM]" in result.message
    assert "`SR-101` Washer repair [start 11:00 AM]" in result.message


def test_dispatch_service_builds_route_map_preview(tmp_path: Path) -> None:
    class RouteMapDispatchAdapter(DummyDispatchAdapter):
        async def build_route_map_urls(self, stops):
            return (
                "https://map.project-osrm.org/?loc=44.2598,-70.5009&loc=43.6591,-70.2568&loc=44.1004,-70.2148",
                "https://maps.geoapify.com/v1/staticmap?style=osm-bright",
            )

    bluefolder_package = tmp_path / "bluefolder_api"
    bluefolder_package.mkdir()
    (bluefolder_package / "__init__.py").write_text("", encoding="utf-8")
    (bluefolder_package / "client.py").write_text(
        textwrap.dedent(
            """
            import xml.etree.ElementTree as ET

            class _Assignments:
                def list_for_user_range(self, user_id, start_date, end_date, date_range_type=None):
                    return [
                        {"serviceRequestId": "100", "start": "2026-03-24T08:00:00"},
                        {"serviceRequestId": "101", "start": "2026-03-24T11:00:00"},
                    ]

            class _ServiceRequests:
                def get_by_id(self, service_request_id: int):
                    root = ET.Element("response")
                    sr = ET.SubElement(root, "serviceRequest")
                    ET.SubElement(sr, "customerId").text = "42"
                    ET.SubElement(sr, "customerLocationId").text = "9"
                    ET.SubElement(sr, "description").text = (
                        "Dryer repair" if service_request_id == 100 else "Washer repair"
                    )
                    return root

            class _Customers:
                def get_location_by_id(self, customer_id: str, location_id: str):
                    root = ET.Element("response")
                    location = ET.SubElement(root, "customerLocation")
                    ET.SubElement(location, "addressStreet").text = (
                        "123 Main St" if customer_id == "42" else "44 Oak St"
                    )
                    ET.SubElement(location, "addressCity").text = (
                        "Portland" if customer_id == "42" else "Lewiston"
                    )
                    ET.SubElement(location, "addressState").text = "ME"
                    ET.SubElement(location, "addressPostalCode").text = (
                        "04101" if customer_id == "42" else "04240"
                    )
                    return root

            class BlueFolderClient:
                def __init__(self, base_url: str | None = None):
                    self.base_url = base_url
                    self.assignments = _Assignments()
                    self.service_requests = _ServiceRequests()
                    self.customers = _Customers()
            """
        ),
        encoding="utf-8",
    )
    service = DispatchService(
        adapter=RouteMapDispatchAdapter(base_path=None),
        bluefolder_service=BlueFolderService(
            adapter=BlueFolderAdapter(
                base_path=str(tmp_path),
                api_key="key",
                account_name="acme",
            )
        ),
    )

    result = asyncio.run(
        service.lookup_route_map(
            JobLookupRequest(
                reference=None,
                requested_by_user_id=1,
                technician_bluefolder_user_id=13051,
            )
        )
    )

    assert "**Route Map for BlueFolder user `13051`**" in result.message
    assert "Assignments considered: `2`" in result.message
    assert "Mappable stops: `2`" in result.message
    assert "Open route: https://map.project-osrm.org/?" in result.message
    assert result.image_url is not None
    assert "maps.geoapify.com/v1/staticmap" in result.image_url


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


def test_bluefolder_adapter_builds_customer_contacts_from_fallback_customer_xml(tmp_path: Path) -> None:
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
                    ET.SubElement(sr, "description").text = "Dryer repair"
                    ET.SubElement(sr, "customerName").text = "Jane Owner"
                    ET.SubElement(sr, "customerContactPhone").text = "207-555-1111"
                    ET.SubElement(sr, "customerId").text = "55"
                    ET.SubElement(sr, "customerLocationId").text = "9"
                    return root

            class _Customers:
                def get_location_by_id(self, customer_id: int, location_id: int):
                    root = ET.Element("response")
                    location = ET.SubElement(root, "customerLocation")
                    ET.SubElement(location, "addressStreet").text = "123 Main St"
                    ET.SubElement(location, "addressCity").text = "Portland"
                    ET.SubElement(location, "addressState").text = "ME"
                    ET.SubElement(location, "addressPostalCode").text = "04101"
                    return root

                def get_by_id(self, customer_id: int):
                    root = ET.Element("response")
                    contact1 = ET.SubElement(root, "customerContact")
                    ET.SubElement(contact1, "firstName").text = "Jane"
                    ET.SubElement(contact1, "lastName").text = "Owner"
                    ET.SubElement(contact1, "phone").text = "207-555-1111"
                    ET.SubElement(contact1, "isPrimary").text = "1"
                    contact2 = ET.SubElement(root, "customerContact")
                    ET.SubElement(contact2, "firstName").text = "Tim"
                    ET.SubElement(contact2, "lastName").text = "Tenant"
                    ET.SubElement(contact2, "phone").text = "207-555-2222"
                    ET.SubElement(contact2, "isPrimary").text = "0"
                    return root

            class _CustomerContacts:
                def list_for_customer(self, customer_id: int):
                    raise RuntimeError("customer contacts unavailable")

            class BlueFolderClient:
                def __init__(self, base_url: str | None = None):
                    self.base_url = base_url
                    self.service_requests = _ServiceRequests()
                    self.customers = _Customers()
                    self.customer_contacts = _CustomerContacts()
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

    assert result.customer_phone == "207-555-1111"
    assert len(result.customer_contacts) == 2
    assert result.customer_contacts[0].name == "Jane Owner"
    assert result.customer_contacts[1].name == "Tim Tenant"
    assert result.customer_contacts[1].phone == "207-555-2222"


def test_bluefolder_service_logs_field_event_and_notifies() -> None:
    class AdapterStub:
        async def add_field_event_comment(self, sr_id, **kwargs):
            assert sr_id == 100
            assert kwargs["event_type"] == "start"
            assert kwargs["details"] == "Beginning diagnosis."
            assert kwargs["requested_by_label"] == "Mike Smith"
            return {
                "ok": True,
                "note_text": "Technician started work at 8:15 AM. Details: Beginning diagnosis.",
                "logged_at": "2026-03-25T08:15",
            }

    class NotificationStub:
        def __init__(self) -> None:
            self.records: list[tuple[str, str]] = []

        async def send_notice(self, *, topic: str, message: str) -> None:
            self.records.append((topic, message))

    notifications = NotificationStub()
    service = BlueFolderService(adapter=AdapterStub(), notifications=notifications)

    result = asyncio.run(
        service.log_field_event(
            100,
            event_type="start",
            details="Beginning diagnosis.",
            requested_by_user_id=42,
            requested_by_label="Mike Smith",
            notify_dispatch=True,
        )
    )

    assert "Logged start for `100`" in result.message
    assert notifications.records == [
        (
            "dispatch.field_update",
            "SR-100 start logged. Technician started work at 8:15 AM. Details: Beginning diagnosis.",
        )
    ]


def test_bluefolder_service_builds_customer_snapshot() -> None:
    class AdapterStub:
        async def get_job_summary(self, reference: str):
            assert reference == "SR-100"
            from ops_hub.models.requests import BlueFolderJobSummary

            return BlueFolderJobSummary(
                reference=reference,
                available=True,
                integration_status="live_read",
                message="ok",
                service_request_id="100",
                subject="Dryer repair",
                customer_name="Jane Doe",
                customer_phone="207-555-1212",
                customer_id="55",
                customer_location_id="9",
                address="123 Main St",
                city="Portland",
                state="ME",
                postal_code="04101",
                service_request_status="Scheduled",
                customer_contacts=(
                    CustomerContactSummary(
                        name="Jane Doe",
                        title="Owner",
                        phone="207-555-1212",
                        email="jane@example.com",
                        is_primary=True,
                    ),
                    CustomerContactSummary(
                        name="John Doe",
                        phone="207-555-2323",
                        is_primary=False,
                    ),
                ),
            )

    service = BlueFolderService(adapter=AdapterStub())

    result = asyncio.run(service.get_customer_snapshot(100))

    assert "**Customer SR-100**" in result.message
    assert "Subject: Dryer repair" in result.message
    assert "Customer: Jane Doe" in result.message
    assert "Phone: 207-555-1212" in result.message
    assert "Status: `Scheduled`" in result.message
    assert "Address: 123 Main St, Portland ME 04101" in result.message
    assert "**Contacts**" in result.message
    assert "Primary: Jane Doe | Owner | 207-555-1212 | jane@example.com" in result.message
    assert "Contact: John Doe | 207-555-2323" in result.message


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
            import xml.etree.ElementTree as ET

            class _ServiceRequests:
                def get_history(self, service_request_id: int):
                    root = ET.Element("response")
                    if service_request_id == 100:
                        entry = ET.SubElement(root, "serviceRequestHistory")
                        ET.SubElement(entry, "entryDate").text = "2026-03-22 10:00"
                        ET.SubElement(entry, "userName").text = "Parts"
                        ET.SubElement(entry, "comment").text = "Part ready for scheduling at 10:00 AM. Details: all parts are in."
                    else:
                        entry = ET.SubElement(root, "serviceRequestHistory")
                        ET.SubElement(entry, "entryDate").text = "2026-03-22 09:00"
                        ET.SubElement(entry, "userName").text = "Parts"
                        ET.SubElement(entry, "comment").text = "Part tracking update: UPS 123"
                    return root

            class BlueFolderClient:
                def __init__(self, base_url: str | None = None):
                    self.base_url = base_url
                    self.service_requests = _ServiceRequests()
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
            import xml.etree.ElementTree as ET

            class _ServiceRequests:
                def get_history(self, service_request_id: int):
                    root = ET.Element("response")
                    entry = ET.SubElement(root, "serviceRequestHistory")
                    ET.SubElement(entry, "entryDate").text = "2026-03-22 10:00" if service_request_id == 100 else "2026-03-22 09:00"
                    ET.SubElement(entry, "userName").text = "Parts"
                    ET.SubElement(entry, "comment").text = (
                        "Part ready for scheduling at 10:00 AM. Details: all parts are in."
                        if service_request_id == 100
                        else "Part received at 9:00 AM. Details: received at shop."
                    )
                    return root

            class BlueFolderClient:
                def __init__(self, base_url: str | None = None):
                    self.base_url = base_url
                    self.service_requests = _ServiceRequests()
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

                def get_history(self, service_request_id: int):
                    root = ET.Element("response")
                    entry = ET.SubElement(root, "serviceRequestHistory")
                    ET.SubElement(entry, "entryDate").text = "2026-03-22 10:00"
                    ET.SubElement(entry, "userName").text = "Parts"
                    ET.SubElement(entry, "comment").text = "Part tracking update: UPS 123"
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
    assert result.service_request_status is None


def test_bluefolder_adapter_reads_service_request_status_when_present(tmp_path: Path) -> None:
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
                    ET.SubElement(sr, "status").text = "Completed"
                    return root

            class BlueFolderClient:
                def __init__(self, base_url: str | None = None):
                    self.base_url = base_url
                    self.service_requests = _ServiceRequests()
                    self.customers = object()
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
    assert result.service_request_status == "Completed"


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

                def get_history(self, service_request_id: int):
                    root = ET.Element("response")
                    entry = ET.SubElement(root, "serviceRequestHistory")
                    ET.SubElement(entry, "entryDate").text = "2026-03-22 10:00"
                    ET.SubElement(entry, "userName").text = "Parts"
                    ET.SubElement(entry, "comment").text = "Tracking update: UPS 123"
                    entry = ET.SubElement(root, "serviceRequestHistory")
                    ET.SubElement(entry, "entryDate").text = "2026-03-22 09:00"
                    ET.SubElement(entry, "userName").text = "Tech"
                    ET.SubElement(entry, "comment").text = "General note"
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


def test_bluefolder_service_returns_parts_brief_when_sr_lookup_fails_but_comments_exist(tmp_path: Path) -> None:
    package_dir = tmp_path / "bluefolder_api"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "client.py").write_text(
        textwrap.dedent(
            """
            class _ServiceRequests:
                def get_by_id(self, service_request_id: int):
                    raise RuntimeError("Invalid XML response")


            import xml.etree.ElementTree as ET

            class _ServiceRequests:
                def get_by_id(self, service_request_id: int):
                    raise RuntimeError("Invalid XML response")

                def get_history(self, service_request_id: int):
                    root = ET.Element("response")
                    entry = ET.SubElement(root, "serviceRequestHistory")
                    ET.SubElement(entry, "entryDate").text = "2026-03-22 10:00"
                    ET.SubElement(entry, "userName").text = "Parts"
                    ET.SubElement(entry, "comment").text = "Part tracking update: UPS 123"
                    return root


            class BlueFolderClient:
                def __init__(self, base_url: str | None = None):
                    self.base_url = base_url
                    self.service_requests = _ServiceRequests()
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
    assert "Status: `lookup_failed`" in result.message
    assert "Parts stage: `Tracking Posted`" in result.message
    assert "Status detail: Part tracking update: UPS 123" in result.message
    assert "Recommended next action: Track shipment progress and prepare dispatch for receipt or scheduling follow-up." in result.message


def test_bluefolder_adapter_returns_no_comments_when_comment_lookup_has_invalid_xml(tmp_path: Path) -> None:
    package_dir = tmp_path / "bluefolder_api"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "client.py").write_text(
        textwrap.dedent(
            """
            class _ServiceRequests:
                def get_history(self, service_request_id: int):
                    raise RuntimeError("Invalid XML response")


            class BlueFolderClient:
                def __init__(self, base_url: str | None = None):
                    self.base_url = base_url
                    self.service_requests = _ServiceRequests()
            """
        ),
        encoding="utf-8",
    )
    adapter = BlueFolderAdapter(
        base_path=str(tmp_path),
        api_key="key",
        account_name="acme",
    )

    result = asyncio.run(adapter.get_recent_parts_comments(100))

    assert result == []


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


            import xml.etree.ElementTree as ET

            class _ServiceRequests:
                def get_history(self, service_request_id: int):
                    root = ET.Element("response")
                    entry = ET.SubElement(root, "serviceRequestHistory")
                    ET.SubElement(entry, "entryDate").text = "2026-03-22 09:00"
                    ET.SubElement(entry, "userName").text = "Tech"
                    ET.SubElement(entry, "comment").text = "Missing part reported at 9:00 AM. Details: belt."
                    return root


            class BlueFolderClient:
                def __init__(self, base_url: str | None = None):
                    self.base_url = base_url
                    self.service_requests = _ServiceRequests()
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

            class _ServiceRequests:
                def get_by_id(self, service_request_id: int):
                    root = ET.Element("response")
                    sr = ET.SubElement(root, "serviceRequest")
                    ET.SubElement(sr, "description").text = f"SR description {service_request_id}"
                    return root

                def get_history(self, service_request_id: int):
                    root = ET.Element("response")
                    entry = ET.SubElement(root, "serviceRequestHistory")
                    ET.SubElement(entry, "entryDate").text = "2026-03-22 10:00"
                    ET.SubElement(entry, "userName").text = "Parts"
                    ET.SubElement(entry, "comment").text = "Part ready for scheduling at 10:00 AM. Details: all parts are in."
                    return root

            class BlueFolderClient:
                def __init__(self, base_url: str | None = None):
                    self.base_url = base_url
                    self.service_requests = _ServiceRequests()
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
            import xml.etree.ElementTree as ET

            class _ServiceRequests:
                def get_history(self, service_request_id: int):
                    root = ET.Element("response")
                    entry = ET.SubElement(root, "serviceRequestHistory")
                    ET.SubElement(entry, "entryDate").text = "2026-03-22 10:00"
                    ET.SubElement(entry, "userName").text = "Parts"
                    ET.SubElement(entry, "comment").text = "Tracking update: UPS 123"
                    entry = ET.SubElement(root, "serviceRequestHistory")
                    ET.SubElement(entry, "entryDate").text = "2026-03-22 09:00"
                    ET.SubElement(entry, "userName").text = "Tech"
                    ET.SubElement(entry, "comment").text = "Missing part reported at 9:00 AM. Details: belt."
                    entry = ET.SubElement(root, "serviceRequestHistory")
                    ET.SubElement(entry, "entryDate").text = "2026-03-22 08:00"
                    ET.SubElement(entry, "userName").text = "Tech"
                    ET.SubElement(entry, "comment").text = "Unrelated note"
                    return root

            class BlueFolderClient:
                def __init__(self, base_url: str | None = None):
                    self.base_url = base_url
                    self.service_requests = _ServiceRequests()
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


def test_bluefolder_service_logs_route_update_and_notifies() -> None:
    class _Adapter:
        async def add_field_event_comment(
            self,
            sr_id,
            *,
            event_type,
            requested_by_user_id,
            requested_by_label=None,
            details=None,
            minutes=None,
        ):
            return {
                "ok": True,
                "logged_at": "2026-03-25T12:30",
                "note_text": "ETA update: arriving in 15 minutes. Reported by Mike Smith.",
            }

    class _Notifications:
        def __init__(self) -> None:
            self.calls = []

        async def send_notice(self, *, topic: str, message: str) -> None:
            self.calls.append((topic, message))

    notifications = _Notifications()
    service = BlueFolderService(adapter=_Adapter(), notifications=notifications)  # type: ignore[arg-type]

    result = asyncio.run(
            service.log_route_update(
                12345,
                update_type="eta",
                requested_by_user_id=42,
                requested_by_label="Mike Smith",
                minutes=15,
                notify_dispatch=True,
            )
        )

    assert "Logged eta for `12345`" in result.message
    assert notifications.calls == [
        ("dispatch.route_update", "SR-12345 eta logged. ETA update: arriving in 15 minutes. Reported by Mike Smith.")
    ]


def test_bluefolder_service_logs_contact_issue_and_notifies() -> None:
    class _Adapter:
        async def add_field_event_comment(
            self,
            sr_id,
            *,
            event_type,
            requested_by_user_id,
            requested_by_label=None,
            details=None,
            minutes=None,
        ):
            return {
                "ok": True,
                "logged_at": "2026-03-25T12:30",
                "note_text": "Customer no-answer at 12:30 PM. Details: knocked twice. Reported by Mike Smith.",
            }

    class _Notifications:
        def __init__(self) -> None:
            self.calls = []

        async def send_notice(self, *, topic: str, message: str) -> None:
            self.calls.append((topic, message))

    notifications = _Notifications()
    service = BlueFolderService(adapter=_Adapter(), notifications=notifications)  # type: ignore[arg-type]

    result = asyncio.run(
            service.log_contact_issue(
                12345,
                issue_type="no_answer",
                details="knocked twice",
                requested_by_user_id=42,
                requested_by_label="Mike Smith",
                notify_dispatch=True,
            )
        )

    assert "Logged no-answer for `12345`" in result.message
    assert notifications.calls == [
        ("dispatch.contact_issue", "SR-12345 no-answer logged. Customer no-answer at 12:30 PM. Details: knocked twice. Reported by Mike Smith.")
    ]
