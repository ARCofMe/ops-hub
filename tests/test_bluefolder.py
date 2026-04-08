"""BlueFolder adapter and service tests for Ops Hub."""

import asyncio
from datetime import datetime
import threading
from time import perf_counter
from pathlib import Path
import textwrap
from types import SimpleNamespace

from ops_hub.integrations.bluefolder_adapter import BlueFolderAdapter
from ops_hub.integrations.dispatch_adapter import DispatchAdapter
from ops_hub.models.requests import (
    AttentionItemRecord,
    CustomerContactSummary,
    JobLookupRequest,
    PartsCaseRecord,
    TechnicianCloseoutDraft,
    TechnicianMappingRecord,
    WorkflowEventRecord,
    WorkflowStateSnapshot,
)
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

    assert result.integration_status in {"import_error", "client_unconfigured"}
    assert result.available is False
    assert result.source_path == tmp_path


def test_bluefolder_adapter_skips_customer_enrichment_when_contacts_are_disabled(tmp_path: Path) -> None:
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
                    ET.SubElement(sr, "description").text = "Dryer repair"
                    ET.SubElement(sr, "serviceRequestStatus").text = "Scheduled"
                    return root

            class _Customers:
                def get_location_by_id(self, customer_id: str, location_id: str):
                    raise AssertionError("customer location lookup should be skipped")

                def get_by_id(self, customer_id: int):
                    raise AssertionError("customer fallback lookup should be skipped")

            class _CustomerContacts:
                def list_for_customer(self, customer_id: int):
                    raise AssertionError("customer contact lookup should be skipped")

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

    result = asyncio.run(adapter.get_job_summary("SR-100", include_customer_contacts=False))

    assert result.available is True
    assert result.subject == "Dryer repair"
    assert result.service_request_status == "Scheduled"
    assert result.address is None
    assert result.customer_contacts == ()


def test_bluefolder_adapter_skips_assignment_subject_lookups_when_disabled(tmp_path: Path) -> None:
    bluefolder_package = tmp_path / "bluefolder_api"
    bluefolder_package.mkdir()
    (bluefolder_package / "__init__.py").write_text("", encoding="utf-8")
    (bluefolder_package / "client.py").write_text(
        textwrap.dedent(
            """
            class _Assignments:
                def list_for_user_range(self, user_id, start_date, end_date, date_range_type=None):
                    return [{"serviceRequestId": "100", "start": "2026-03-24T08:00:00"}]

            class _ServiceRequests:
                def get_by_id(self, service_request_id: int):
                    raise AssertionError("service request subject lookup should be skipped")

            class BlueFolderClient:
                def __init__(self, base_url: str | None = None):
                    self.base_url = base_url
                    self.assignments = _Assignments()
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

    assignments = asyncio.run(
        adapter.get_assignments_for_user_on_date(13051, day=__import__("datetime").date(2026, 3, 24), include_subjects=False)
    )

    assert len(assignments) == 1
    assert assignments[0]["serviceRequestId"] == "100"
    assert assignments[0]["subject"] == "Service Request"


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
    assert (
        "Status: `import_error`" in result.message
        or "Status: `client_unconfigured`" in result.message
    )
    assert (
        "Failed to import bluefolder_api from configured path" in result.message
        or "BlueFolder API key is not configured for Ops Hub." in result.message
    )
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


def test_dispatch_adapter_route_map_includes_all_stops_and_custom_endpoints(monkeypatch) -> None:
    adapter = DispatchAdapter(base_path=None)

    def fake_env(_resolved_path):
        return {"GEOAPIFY_API_KEY": "geo-key", "DEFAULT_ORIGIN": "Shop"}

    coords = {
        "Custom Start": (-70.50, 44.25),
        "Stop 1": (-70.25, 43.65),
        "Stop 2": (-70.21, 44.10),
        "Stop 3": (-70.12, 44.20),
        "Custom End": (-70.05, 44.30),
    }

    def fake_geocode(address, *, api_key):
        assert api_key == "geo-key"
        return coords.get(address)

    monkeypatch.setattr(DispatchAdapter, "_load_dispatch_project_env", lambda self, resolved_path: fake_env(resolved_path))
    monkeypatch.setattr(
        DispatchAdapter,
        "_geocode_address_geoapify",
        lambda self, address, *, api_key: fake_geocode(address, api_key=api_key),
    )

    route_url, image_url = asyncio.run(
        adapter.build_route_map_urls(
            [
                {"address": "Stop 1"},
                {"address": "Stop 2"},
                {"address": "Stop 3"},
            ],
            origin_address="Custom Start",
            destination_address="Custom End",
        )
    )

    assert route_url is not None
    assert route_url.count("loc=") == 5
    assert image_url is not None
    assert "text%3AO" in image_url
    assert "text%3A1" in image_url
    assert "text%3A2" in image_url
    assert "text%3A3" in image_url
    assert "text%3AD" in image_url


def test_dispatch_adapter_builds_heat_map_url(monkeypatch) -> None:
    adapter = DispatchAdapter(base_path=None)

    monkeypatch.setattr(
        DispatchAdapter,
        "_load_dispatch_project_env",
        lambda self, resolved_path: {"GEOAPIFY_API_KEY": "geo-key"},
    )
    monkeypatch.setattr(
        DispatchAdapter,
        "_geocode_address_geoapify",
        lambda self, address, *, api_key: {
            "A": (-70.1, 44.1),
            "B": (-70.2, 44.2),
        }.get(address),
    )

    image_url = asyncio.run(
        adapter.build_heat_map_url(
            [
                {"address": "A", "count": 3},
                {"address": "B", "count": 1},
            ]
        )
    )

    assert image_url is not None
    assert "maps.geoapify.com/v1/staticmap" in image_url
    assert "text%3A3" in image_url
    assert "text%3A1" in image_url


def test_dispatch_service_builds_assignment_heatmap(tmp_path: Path) -> None:
    class HeatMapDispatchAdapter(DummyDispatchAdapter):
        async def build_heat_map_url(self, hotspots):
            assert len(hotspots) == 1
            assert hotspots[0]["count"] == 3
            return "https://maps.geoapify.com/v1/staticmap?style=osm-bright"

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
                        {"serviceRequestId": "102", "start": "2026-03-24T13:00:00"},
                    ]

            class _ServiceRequests:
                def get_by_id(self, service_request_id: int):
                    root = ET.Element("response")
                    sr = ET.SubElement(root, "serviceRequest")
                    ET.SubElement(sr, "customerId").text = "42"
                    ET.SubElement(sr, "customerLocationId").text = "9"
                    ET.SubElement(sr, "description").text = f"Job {service_request_id}"
                    return root

            class _Customers:
                def get_location_by_id(self, customer_id: str, location_id: str):
                    root = ET.Element("response")
                    location = ET.SubElement(root, "customerLocation")
                    ET.SubElement(location, "addressStreet").text = (
                        "123 Main St" if location_id == "9" else "44 Oak St"
                    )
                    ET.SubElement(location, "addressCity").text = (
                        "Portland" if location_id == "9" else "Lewiston"
                    )
                    ET.SubElement(location, "addressState").text = "ME"
                    ET.SubElement(location, "addressPostalCode").text = (
                        "04101" if location_id == "9" else "04240"
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
        adapter=HeatMapDispatchAdapter(base_path=None),
        bluefolder_service=BlueFolderService(
            adapter=BlueFolderAdapter(
                base_path=str(tmp_path),
                api_key="key",
                account_name="acme",
            )
        ),
    )

    result = asyncio.run(
        service.lookup_assignment_heatmap(
            [TechnicianMappingRecord(discord_user_id=1, bluefolder_user_id=13051)]
        )
    )

    assert "**Dispatch Heatmap**" in result.message
    assert "Scanned jobs: `3`" in result.message
    assert "Unique mapped locations: `1`" in result.message
    assert result.image_url is not None


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


def test_bluefolder_adapter_skips_non_xml_customer_fallback_payload(tmp_path: Path) -> None:
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
                    ET.SubElement(sr, "customerId").text = "55"
                    ET.SubElement(sr, "customerLocationId").text = "9"
                    return root

            class _Customers:
                def get_location_by_id(self, customer_id: int, location_id: int):
                    root = ET.Element("response")
                    ET.SubElement(root, "customerLocation")
                    return root

                def get_by_id(self, customer_id: int):
                    return "<html>not xml</html>"

            class _CustomerContacts:
                def list_for_customer(self, customer_id: int):
                    raise RuntimeError("404 Client Error: Not Found for url: /api/2.0/customerContacts/list.aspx")

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

    assert result.available is True
    assert result.customer_phone is None
    assert result.customer_contacts == ()


def test_bluefolder_adapter_disables_missing_customer_contacts_endpoint_after_first_404(tmp_path: Path) -> None:
    bluefolder_package = tmp_path / "bluefolder_api"
    bluefolder_package.mkdir()
    (bluefolder_package / "__init__.py").write_text("", encoding="utf-8")
    (bluefolder_package / "client.py").write_text(
        textwrap.dedent(
            """
            import xml.etree.ElementTree as ET

            contact_calls = 0

            class _ServiceRequests:
                def get_by_id(self, service_request_id: int):
                    root = ET.Element("response")
                    sr = ET.SubElement(root, "serviceRequest")
                    ET.SubElement(sr, "description").text = "Dryer repair"
                    ET.SubElement(sr, "customerId").text = "55"
                    ET.SubElement(sr, "customerLocationId").text = "9"
                    return root

            class _Customers:
                def get_location_by_id(self, customer_id: int, location_id: int):
                    root = ET.Element("response")
                    ET.SubElement(root, "customerLocation")
                    return root

                def get_by_id(self, customer_id: int):
                    root = ET.Element("response")
                    contact = ET.SubElement(root, "customerContact")
                    ET.SubElement(contact, "firstName").text = "Jane"
                    ET.SubElement(contact, "lastName").text = "Owner"
                    ET.SubElement(contact, "phone").text = "207-555-1111"
                    ET.SubElement(contact, "isPrimary").text = "1"
                    return root

            class _CustomerContacts:
                def list_for_customer(self, customer_id: int):
                    global contact_calls
                    contact_calls += 1
                    raise RuntimeError("404 Client Error: Not Found for url: /api/2.0/customerContacts/list.aspx")

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

    first = asyncio.run(adapter.get_job_summary("SR-100"))
    second = asyncio.run(adapter.get_job_summary("SR-100"))

    assert first.customer_contacts[0].name == "Jane Owner"
    assert second.customer_contacts[0].name == "Jane Owner"
    assert adapter._customer_contacts_endpoint_unavailable is True


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
    assert "Actionable stages: `New SR Triage`, `Model/Serial Needed`, `Likely Parts Previsit`" in result.message
    assert "1. `SR-100` Dryer repair" in result.message
    assert "Stage: `Ready for Scheduling`" in result.message
    assert "Technician: BlueFolder user `13051`" in result.message
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
    (tmp_path / ".env").write_text(
        "DEFAULT_ORIGIN=South Paris, ME\nGEOAPIFY_API_KEY=test-key\n",
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
    assert "Dispatch default origin: South Paris, ME" in result.message
    assert "Dispatch route tools: route map `ready`, heatmap `ready`" in result.message
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
    assert result.route_map_supported is False
    assert result.heat_map_supported is False


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
            class _ServiceRequests:
                def __init__(self):
                    self.calls = []

                def add_comment(self, service_request_id: int, text: str, comment_is_public: bool = False, user_id: int | None = None):
                    self.calls.append((service_request_id, text, comment_is_public, user_id))
                    return {"ok": True}

            _shared_service_requests = _ServiceRequests()

            class BlueFolderClient:
                def __init__(self, base_url: str | None = None):
                    self.base_url = base_url
                    self.service_requests = _shared_service_requests
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
            class _ServiceRequests:
                def __init__(self):
                    self.calls = []

                def add_comment(self, service_request_id: int, text: str, comment_is_public: bool = False, user_id: int | None = None):
                    self.calls.append((service_request_id, text, comment_is_public, user_id))
                    return {"ok": True}

            _shared_service_requests = _ServiceRequests()

            class BlueFolderClient:
                def __init__(self, base_url: str | None = None):
                    self.base_url = base_url
                    self.service_requests = _shared_service_requests
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
            bluefolder_user_id=None,
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
            bluefolder_user_id=None,
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


def test_dispatch_service_returns_structured_board_payload() -> None:
    async def get_assignments_for_user_on_date(user_id: int, day):
        _ = (user_id, day)
        return [{"serviceRequestId": "100", "subject": "Dryer repair"}]

    attention_item = AttentionItemRecord(
        item_id="dispatch:SR-100:quote_needed:landlord",
        sr_id=100,
        reference="SR-100",
        category="dispatch",
        status="open",
        stage="quote_needed",
        stage_label="Quote Needed",
        summary="Dryer repair",
        owner_discord_user_id=42,
        owner_bluefolder_user_id=13051,
        assigned_owner_discord_user_id=99,
        age_hours=3,
        age_bucket="warm",
    )
    parts_case = PartsCaseRecord(
        case_id="parts:SR-100",
        reference="SR-100",
        sr_id=100,
        stage="ordered",
        stage_label="Ordered",
        status="open",
        open_request_ids=[7],
        next_action="Wait for ETA.",
        age_hours=12,
        age_bucket="warm",
    )
    workflow_state = SimpleNamespace(
        refresh_dispatch_attention=lambda mappings: asyncio.sleep(0, result=(1, [attention_item])),
        current_snapshot=lambda: WorkflowStateSnapshot(
            attention_items=[attention_item],
            parts_cases=[parts_case],
            events=[],
            updated_at="2026-04-01T10:00:00Z",
        ),
        attention_metrics=lambda snapshot: {
            "total_items": 1,
            "status_counts": {"open": 1},
            "stage_counts": {"Quote Needed": 1},
            "age_counts": {"warm": 1},
            "assigned_owner_items": 1,
            "unassigned_owner_items": 0,
            "urgent_open_items": 0,
            "urgent_suppressed_items": 0,
        },
    )
    directory = SimpleNamespace(
        mapping_records=lambda: [TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051)],
        reverse_mappings=lambda: {13051: 42},
        display_label=lambda user_id: None,
        discord_mention=lambda user_id: f"<@{user_id}>",
    )
    bluefolder_service = SimpleNamespace(
        get_assignments_for_user_on_date=get_assignments_for_user_on_date,
        get_user_name=lambda user_id: asyncio.sleep(0, result=None),
    )
    service = DispatchService(
        adapter=DummyDispatchAdapter(base_path=None),
        bluefolder_service=bluefolder_service,
        technician_directory_service=directory,
        workflow_state_service=workflow_state,
    )

    payload = asyncio.run(service.get_dispatch_board_payload())

    assert payload["mappedTechs"] == 1
    assert payload["attentionJobs"] == 1
    assert payload["topAttention"][0]["itemId"] == "dispatch:SR-100:quote_needed:landlord"
    assert payload["openPartsCaseItems"][0]["reference"] == "SR-100"


def test_dispatch_service_board_prefers_bluefolder_user_name_for_technician_label() -> None:
    async def get_assignments_for_user_on_date(user_id: int, day, include_subjects: bool = True):
        _ = (user_id, day)
        return [{"serviceRequestId": "100", "subject": "Dryer repair"}]

    directory = SimpleNamespace(
        mapping_records=lambda: [TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051)],
        reverse_mappings=lambda: {13051: 42},
        display_label=lambda user_id: "Dispatch Dave" if user_id == 42 else None,
        discord_mention=lambda user_id: f"<@{user_id}>",
    )
    bluefolder_service = SimpleNamespace(
        get_assignments_for_user_on_date=get_assignments_for_user_on_date,
        get_user_name=lambda user_id: asyncio.sleep(0, result="Pat Tech" if user_id == 13051 else None),
    )
    service = DispatchService(
        adapter=DummyDispatchAdapter(base_path=None),
        bluefolder_service=bluefolder_service,
        technician_directory_service=directory,
        workflow_state_service=None,
    )

    payload = asyncio.run(service.get_dispatch_board_payload())

    assert payload["technicianLoad"][0]["technicianLabel"] == "Pat Tech"


def test_dispatch_service_board_filters_dispatch_only_bluefolder_users() -> None:
    async def get_assignments_for_user_on_date(user_id: int, day, include_subjects: bool = True):
        _ = (user_id, day, include_subjects)
        return [{"serviceRequestId": "100", "subject": "Dryer repair"}]

    class _Directory:
        async def operator_records(self, *, bluefolder_service=None):
            _ = bluefolder_service
            return [
                TechnicianMappingRecord(
                    discord_user_id=None,
                    bluefolder_user_id=9001,
                    bluefolder_name="Dispatch Dana",
                    bluefolder_user_type="Dispatch",
                    bluefolder_role="dispatch",
                ),
                TechnicianMappingRecord(
                    discord_user_id=None,
                    bluefolder_user_id=9002,
                    bluefolder_name="Field Sam",
                    bluefolder_user_type="Technician",
                    bluefolder_role="technician",
                ),
            ]

        def reverse_mappings(self):
            return {}

        def display_label(self, user_id):
            _ = user_id
            return None

        def discord_mention(self, user_id):
            return f"<@{user_id}>"

    bluefolder_service = SimpleNamespace(
        get_assignments_for_user_on_date=get_assignments_for_user_on_date,
        get_user_name=lambda user_id: asyncio.sleep(0, result="Field Sam" if user_id == 9002 else "Dispatch Dana"),
    )
    service = DispatchService(
        adapter=DummyDispatchAdapter(base_path=None),
        bluefolder_service=bluefolder_service,
        technician_directory_service=_Directory(),
        workflow_state_service=None,
    )

    payload = asyncio.run(service.get_dispatch_board_payload())

    assert payload["visibleOperators"] == 2
    assert payload["mappedTechs"] == 1
    assert [entry["technicianLabel"] for entry in payload["technicianLoad"]] == ["Field Sam"]
    assert payload["technicianLoad"][0]["bluefolderRole"] == "technician"


def test_dispatch_service_board_loads_technicians_concurrently() -> None:
    mappings = [
        TechnicianMappingRecord(discord_user_id=41, bluefolder_user_id=13051),
        TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13052),
        TechnicianMappingRecord(discord_user_id=43, bluefolder_user_id=13053),
    ]

    async def get_assignments_for_user_on_date(user_id: int, day, include_subjects: bool = True):
        _ = (user_id, day)
        await asyncio.sleep(0.05)
        return [{"serviceRequestId": str(user_id), "subject": f"Job {user_id}"}]

    class SlowDispatchAdapter(DummyDispatchAdapter):
        async def get_origin_for_user(self, technician_bluefolder_user_id: int) -> str | None:
            await asyncio.sleep(0.05)
            return f"Origin {technician_bluefolder_user_id}"

    directory = SimpleNamespace(
        mapping_records=lambda: mappings,
        reverse_mappings=lambda: {record.bluefolder_user_id: record.discord_user_id for record in mappings},
        display_label=lambda user_id: None,
        discord_mention=lambda user_id: f"<@{user_id}>",
    )
    bluefolder_service = SimpleNamespace(
        get_assignments_for_user_on_date=get_assignments_for_user_on_date,
        get_user_name=lambda user_id: asyncio.sleep(0.05, result=f"Tech {user_id}"),
    )
    service = DispatchService(
        adapter=SlowDispatchAdapter(base_path=None),
        bluefolder_service=bluefolder_service,
        technician_directory_service=directory,
        workflow_state_service=None,
    )

    started_at = perf_counter()
    payload = asyncio.run(service.get_dispatch_board_payload())
    elapsed = perf_counter() - started_at

    assert payload["mappedTechs"] == 3
    assert len(payload["technicianLoad"]) == 3
    assert elapsed < 0.18


def test_dispatch_service_board_uses_stale_snapshot_without_blocking_refresh() -> None:
    workflow_state = SimpleNamespace(
        current_snapshot=lambda: WorkflowStateSnapshot(
            attention_items=[
                AttentionItemRecord(
                    item_id="dispatch:SR-100:part_ready",
                    sr_id=100,
                    reference="SR-100",
                    category="dispatch",
                    status="open",
                    stage="part_ready",
                    stage_label="Ready for Scheduling",
                    summary="Dryer repair",
                )
            ],
            parts_cases=[],
            events=[],
            updated_at="2026-04-01T10:00:00Z",
        ),
        attention_metrics=lambda snapshot: {"queueCounts": {"part_ready": 1}},
        refresh_dispatch_attention=lambda mappings: asyncio.sleep(0.2, result=(1, [])),
    )
    directory = SimpleNamespace(
        mapping_records=lambda: [TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051)],
        reverse_mappings=lambda: {13051: 42},
        display_label=lambda user_id: None,
        discord_mention=lambda user_id: f"<@{user_id}>",
    )
    bluefolder_service = SimpleNamespace(
        get_assignments_for_user_on_date=lambda user_id, day, include_subjects=True: asyncio.sleep(
            0, result=[{"serviceRequestId": "100", "subject": "Dryer repair"}]
        ),
        get_user_name=lambda user_id: asyncio.sleep(0, result="Pat Tech"),
    )
    service = DispatchService(
        adapter=DummyDispatchAdapter(base_path=None),
        bluefolder_service=bluefolder_service,
        technician_directory_service=directory,
        workflow_state_service=workflow_state,
    )

    started_at = perf_counter()
    payload = asyncio.run(service.get_dispatch_board_payload())
    elapsed = perf_counter() - started_at

    assert payload["attentionJobs"] == 1
    assert elapsed < 0.15


def test_dispatch_service_board_cold_start_does_not_block_on_refresh() -> None:
    workflow_state = SimpleNamespace(
        current_snapshot=lambda: WorkflowStateSnapshot(
            attention_items=[],
            parts_cases=[],
            events=[],
            updated_at=None,
        ),
        attention_metrics=lambda snapshot: {"queueCounts": {}},
        refresh_dispatch_attention=lambda mappings: asyncio.sleep(0.2, result=(1, [])),
    )
    directory = SimpleNamespace(
        mapping_records=lambda: [TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051)],
        reverse_mappings=lambda: {13051: 42},
        display_label=lambda user_id: None,
        discord_mention=lambda user_id: f"<@{user_id}>",
    )
    bluefolder_service = SimpleNamespace(
        get_assignments_for_user_on_date=lambda user_id, day, include_subjects=True: asyncio.sleep(
            0, result=[{"serviceRequestId": "100", "subject": "Dryer repair"}]
        ),
        get_user_name=lambda user_id: asyncio.sleep(0, result="Pat Tech"),
    )
    service = DispatchService(
        adapter=DummyDispatchAdapter(base_path=None),
        bluefolder_service=bluefolder_service,
        technician_directory_service=directory,
        workflow_state_service=workflow_state,
    )

    started_at = perf_counter()
    payload = asyncio.run(service.get_dispatch_board_payload())
    elapsed = perf_counter() - started_at

    assert payload["attentionJobs"] == 0
    assert payload["scannedJobs"] == 0
    assert elapsed < 0.15


def test_dispatch_service_attention_uses_snapshot_without_blocking_refresh() -> None:
    workflow_state = SimpleNamespace(
        current_snapshot=lambda: WorkflowStateSnapshot(
            attention_items=[
                AttentionItemRecord(
                    item_id="dispatch:SR-100:quote_needed",
                    sr_id=100,
                    reference="SR-100",
                    category="dispatch",
                    status="open",
                    stage="quote_needed",
                    stage_label="Quote Needed",
                    summary="Dryer repair",
                )
            ],
            parts_cases=[],
            events=[],
            updated_at="2026-04-01T10:00:00Z",
        ),
        refresh_dispatch_attention=lambda mappings, **kwargs: asyncio.sleep(0.2, result=(1, [])),
    )
    directory = SimpleNamespace(
        mapping_records=lambda: [TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051)],
        reverse_mappings=lambda: {13051: 42},
        display_label=lambda user_id: None,
        discord_mention=lambda user_id: f"<@{user_id}>",
        operator_records=lambda **kwargs: asyncio.sleep(
            0, result=[TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051)]
        ),
    )
    bluefolder_service = SimpleNamespace(
        get_user_name=lambda user_id: asyncio.sleep(0, result="Pat Tech"),
    )
    service = DispatchService(
        adapter=DummyDispatchAdapter(base_path=None),
        bluefolder_service=bluefolder_service,
        technician_directory_service=directory,
        workflow_state_service=workflow_state,
    )

    started_at = perf_counter()
    payload = asyncio.run(service.get_dispatch_attention_payload())
    elapsed = perf_counter() - started_at

    assert len(payload["items"]) == 1
    assert payload["items"][0]["itemId"] == "dispatch:SR-100:quote_needed"
    assert elapsed < 0.15


def test_dispatch_attention_owner_options_prefer_bluefolder_names() -> None:
    workflow_state = SimpleNamespace(
        current_snapshot=lambda: WorkflowStateSnapshot(
            attention_items=[],
            parts_cases=[],
            events=[],
            updated_at="2026-04-01T10:00:00Z",
        ),
        refresh_dispatch_attention=lambda mappings, **kwargs: asyncio.sleep(0, result=(0, [])),
    )
    directory = SimpleNamespace(
        reverse_mappings=lambda: {},
        display_label=lambda user_id: "discord_danny",
        discord_mention=lambda user_id: f"<@{user_id}>",
        operator_records=lambda **kwargs: asyncio.sleep(
            0,
            result=[
                TechnicianMappingRecord(
                    discord_user_id=42,
                    bluefolder_user_id=2001,
                    bluefolder_name="Danny Marquez",
                    bluefolder_role="dispatch",
                    bluefolder_roles=("Lead Technician", "Service Manager"),
                    username="discord_danny",
                )
            ],
        ),
        dispatch_owner_records=lambda **kwargs: asyncio.sleep(
            0,
            result=[
                TechnicianMappingRecord(
                    discord_user_id=42,
                    bluefolder_user_id=2001,
                    bluefolder_name="Danny Marquez",
                    bluefolder_role="dispatch",
                    bluefolder_roles=("Lead Technician", "Service Manager"),
                    username="discord_danny",
                )
            ],
        ),
    )
    bluefolder_service = SimpleNamespace(
        get_user_name=lambda user_id: asyncio.sleep(0, result="Danny Marquez"),
    )
    service = DispatchService(
        adapter=DummyDispatchAdapter(base_path=None),
        bluefolder_service=bluefolder_service,
        technician_directory_service=directory,
        workflow_state_service=workflow_state,
    )

    payload = asyncio.run(service.get_dispatch_attention_payload())

    assert payload["ownerOptions"][0]["label"] == "Danny Marquez"


def test_dispatch_service_attention_cold_start_refreshes_before_returning() -> None:
    workflow_state = SimpleNamespace(
        current_snapshot=lambda: WorkflowStateSnapshot(
            attention_items=[],
            parts_cases=[],
            events=[],
            updated_at=None,
        ),
        refresh_dispatch_attention=lambda mappings, **kwargs: asyncio.sleep(
            0,
            result=(
                1,
                [
                    AttentionItemRecord(
                        item_id="dispatch:SR-100:quote_needed",
                        sr_id=100,
                        reference="SR-100",
                        category="dispatch",
                        status="open",
                        stage="quote_needed",
                        stage_label="Quote Needed",
                        summary="Dryer repair",
                    )
                ],
            ),
        ),
    )
    directory = SimpleNamespace(
        mapping_records=lambda: [TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051)],
        reverse_mappings=lambda: {13051: 42},
        display_label=lambda user_id: None,
        discord_mention=lambda user_id: f"<@{user_id}>",
        operator_records=lambda **kwargs: asyncio.sleep(
            0, result=[TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051)]
        ),
    )
    bluefolder_service = SimpleNamespace(
        get_user_name=lambda user_id: asyncio.sleep(0, result="Pat Tech"),
    )
    service = DispatchService(
        adapter=DummyDispatchAdapter(base_path=None),
        bluefolder_service=bluefolder_service,
        technician_directory_service=directory,
        workflow_state_service=workflow_state,
    )

    started_at = perf_counter()
    payload = asyncio.run(service.get_dispatch_attention_payload())
    elapsed = perf_counter() - started_at

    assert len(payload["items"]) == 1
    assert payload["items"][0]["itemId"] == "dispatch:SR-100:quote_needed"
    assert payload["scannedJobs"] == 1
    assert elapsed < 0.15


def test_dispatch_service_board_uses_recent_snapshot_without_blocking_refresh() -> None:
    workflow_state = SimpleNamespace(
        current_snapshot=lambda: WorkflowStateSnapshot(
            attention_items=[
                AttentionItemRecord(
                    item_id="dispatch:SR-100:part_ready",
                    sr_id=100,
                    reference="SR-100",
                    category="dispatch",
                    status="open",
                    stage="part_ready",
                    stage_label="Ready for Scheduling",
                    summary="Dryer repair",
                )
            ],
            parts_cases=[
                PartsCaseRecord(
                    case_id="SR-100",
                    reference="SR-100",
                    sr_id=100,
                    stage="part_ready",
                    stage_label="Ready for Scheduling",
                    status="open",
                    updated_at=datetime.now().isoformat(),
                )
            ],
            events=[],
            updated_at=datetime.now().isoformat(),
        ),
        attention_metrics=lambda snapshot: {"queueCounts": {"part_ready": 1}},
        refresh_dispatch_attention=lambda mappings: asyncio.sleep(0.2, result=(1, [])),
    )
    directory = SimpleNamespace(
        mapping_records=lambda: [TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051)],
        reverse_mappings=lambda: {13051: 42},
        display_label=lambda user_id: None,
        discord_mention=lambda user_id: f"<@{user_id}>",
    )
    bluefolder_service = SimpleNamespace(
        get_assignments_for_user_on_date=lambda user_id, day, include_subjects=True: asyncio.sleep(
            0, result=[{"serviceRequestId": "100", "subject": "Dryer repair"}]
        ),
        get_user_name=lambda user_id: asyncio.sleep(0, result="Pat Tech"),
    )
    service = DispatchService(
        adapter=DummyDispatchAdapter(base_path=None),
        bluefolder_service=bluefolder_service,
        technician_directory_service=directory,
        workflow_state_service=workflow_state,
    )

    started_at = perf_counter()
    payload = asyncio.run(service.get_dispatch_board_payload())
    elapsed = perf_counter() - started_at

    assert payload["attentionJobs"] == 1
    assert payload["openPartsCases"] == 1
    assert elapsed < 0.15


def test_dispatch_service_board_background_refresh_warms_photo_compliance() -> None:
    warmed: list[int] = []
    refresh_started = threading.Event()
    refresh_finished = threading.Event()

    async def refresh_dispatch_attention(mappings):
        _ = mappings
        refresh_started.set()
        return 1, []

    async def warm_photo_compliance_for_sr_ids(sr_ids, force: bool = False):
        _ = force
        warmed.extend(sr_ids)
        refresh_finished.set()
        return len(sr_ids)

    workflow_state = SimpleNamespace(
        current_snapshot=lambda: WorkflowStateSnapshot(
            attention_items=[
                AttentionItemRecord(
                    item_id="dispatch:SR-100:part_ready",
                    sr_id=100,
                    reference="SR-100",
                    category="dispatch",
                    status="open",
                    stage="part_ready",
                    stage_label="Ready for Scheduling",
                    summary="Dryer repair",
                )
            ],
            parts_cases=[],
            events=[],
            updated_at=datetime.now().isoformat(),
        ),
        attention_metrics=lambda snapshot: {"queueCounts": {"part_ready": 1}},
        refresh_dispatch_attention=refresh_dispatch_attention,
        warm_photo_compliance_for_sr_ids=warm_photo_compliance_for_sr_ids,
    )
    directory = SimpleNamespace(
        mapping_records=lambda: [TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051)],
        reverse_mappings=lambda: {13051: 42},
        display_label=lambda user_id: None,
        discord_mention=lambda user_id: f"<@{user_id}>",
    )
    bluefolder_service = SimpleNamespace(
        get_assignments_for_user_on_date=lambda user_id, day, include_subjects=True: asyncio.sleep(
            0, result=[{"serviceRequestId": "100", "subject": "Dryer repair"}]
        ),
        get_user_name=lambda user_id: asyncio.sleep(0, result="Pat Tech"),
    )
    service = DispatchService(
        adapter=DummyDispatchAdapter(base_path=None),
        bluefolder_service=bluefolder_service,
        technician_directory_service=directory,
        workflow_state_service=workflow_state,
    )

    payload = asyncio.run(service.get_dispatch_board_payload())

    assert payload["attentionJobs"] == 1
    assert refresh_started.wait(timeout=1.0)
    assert refresh_finished.wait(timeout=1.0)
    assert warmed == [100]


def test_dispatch_service_returns_attention_item_detail_payload() -> None:
    attention_item = AttentionItemRecord(
        item_id="dispatch:SR-100:quote_needed:landlord",
        sr_id=100,
        reference="SR-100",
        category="dispatch",
        status="open",
        stage="quote_needed",
        stage_label="Quote Needed",
        summary="Dryer repair",
        owner_discord_user_id=42,
        owner_bluefolder_user_id=13051,
    )
    workflow_event = WorkflowEventRecord(
        event_id="evt-1",
        event_type="attention_owner_assigned",
        source="ops_hub.dispatch",
        occurred_at="2026-04-01T11:00:00Z",
        summary="Assigned dispatch attention owner for SR-100.",
        sr_id=100,
        reference="SR-100",
    )
    workflow_state = SimpleNamespace(
        get_attention_item=lambda item_id: attention_item,
        attention_history=lambda item_id: [workflow_event],
    )
    directory = SimpleNamespace(
        reverse_mappings=lambda: {13051: 42},
        discord_mention=lambda user_id: f"<@{user_id}>",
    )
    bluefolder_service = SimpleNamespace(get_user_name=lambda user_id: asyncio.sleep(0, result=None))
    service = DispatchService(
        adapter=DummyDispatchAdapter(base_path=None),
        bluefolder_service=bluefolder_service,
        technician_directory_service=directory,
        workflow_state_service=workflow_state,
    )

    payload = asyncio.run(service.get_dispatch_attention_item_payload(item_id=attention_item.item_id))

    assert payload["item"]["itemId"] == attention_item.item_id
    assert payload["item"]["ownerLabel"] == "BlueFolder user `13051`"
    assert payload["item"]["technicianLabel"] == payload["item"]["ownerLabel"]
    assert payload["history"][0]["eventType"] == "attention_owner_assigned"


def test_dispatch_service_returns_structured_sr_customer_payload() -> None:
    async def get_job_summary(reference: str):
        _ = reference
        return SimpleNamespace(
            available=True,
            integration_status="live_read",
            message="ok",
            service_request_id="100",
            subject="Dryer repair",
            customer_name="Pat",
            customer_phone="555-0100",
            service_request_status="Scheduled",
            address="123 Main St",
            city="Portland",
            state="ME",
            postal_code="04101",
            customer_id="77",
            customer_location_id="88",
            customer_contacts=(
                SimpleNamespace(name="Pat", title="Owner", phone="555-0100", email="pat@example.com", is_primary=True),
            ),
        )

    service = DispatchService(
        adapter=DummyDispatchAdapter(base_path=None),
        bluefolder_service=SimpleNamespace(get_job_summary=get_job_summary),
    )

    payload = asyncio.run(service.get_dispatch_sr_customer_payload(sr_id=100))

    assert payload["reference"] == "SR-100"
    assert payload["customerName"] == "Pat"
    assert payload["contacts"][0]["isPrimary"] is True


def test_dispatch_service_returns_structured_sr_timeline_payload() -> None:
    async def build_service_request_timeline(sr_id: int):
        _ = sr_id
        return SimpleNamespace(
            sr_id=100,
            reference="SR-100",
            entries=[
                SimpleNamespace(
                    occurred_at="2026-04-01T12:00:00Z",
                    source="ops_hub.dispatch",
                    event_type="attention_acknowledged",
                    summary="Acknowledged dispatch attention for SR-100.",
                    details="Quote Needed",
                    actor_label="<@99>",
                )
            ],
        )

    service = DispatchService(
        adapter=DummyDispatchAdapter(base_path=None),
        bluefolder_service=SimpleNamespace(),
        workflow_state_service=SimpleNamespace(build_service_request_timeline=build_service_request_timeline),
    )

    payload = asyncio.run(service.get_dispatch_sr_timeline_payload(sr_id=100))

    assert payload["reference"] == "SR-100"
    assert payload["entries"][0]["eventType"] == "attention_acknowledged"


def test_dispatch_service_returns_sms_capabilities_payload() -> None:
    async def get_job_summary(reference: str, include_customer_contacts: bool = True):
        _ = reference, include_customer_contacts
        return SimpleNamespace(
            available=True,
            integration_status="live_read",
            message="ok",
            service_request_id="100",
            subject="Dryer repair",
            customer_name="Pat",
            customer_phone="555-0100",
            service_request_status="Quote Needed",
            address="123 Main St",
            city="Portland",
            state="ME",
            postal_code="04101",
            customer_id="77",
            customer_location_id="88",
            customer_contacts=(),
        )

    service = DispatchService(
        adapter=DummyDispatchAdapter(base_path=None),
        bluefolder_service=SimpleNamespace(get_job_summary=get_job_summary),
        sms_service=SimpleNamespace(
            capabilities_payload=lambda **_: {
                "provider": "dry_run",
                "enabled": True,
                "toNumber": "555-0100",
                "intents": [{"key": "dispatch_quote_follow_up", "label": "Quote follow-up", "recommended": "true"}],
            }
        ),
    )

    payload = asyncio.run(service.get_dispatch_sr_sms_capabilities_payload(sr_id=100))

    assert payload["enabled"] is True
    assert payload["toNumber"] == "555-0100"


def test_dispatch_service_sends_sr_sms_payload() -> None:
    async def get_job_summary(reference: str, include_customer_contacts: bool = True):
        _ = reference, include_customer_contacts
        return SimpleNamespace(
            available=True,
            integration_status="live_read",
            message="ok",
            service_request_id="100",
            subject="Dryer repair",
            customer_name="Pat",
            customer_phone="555-0100",
            service_request_status="Scheduled",
            address="123 Main St",
            city="Portland",
            state="ME",
            postal_code="04101",
            customer_id="77",
            customer_location_id="88",
            customer_contacts=(),
        )

    async def send_payload(**kwargs):
        return {
            "success": True,
            "provider": "dry_run",
            "status": "dry_run",
            "toNumber": kwargs["customer"]["customerPhone"],
            "message": "ARCoM Ops: Test",
        }

    service = DispatchService(
        adapter=DummyDispatchAdapter(base_path=None),
        bluefolder_service=SimpleNamespace(get_job_summary=get_job_summary),
        sms_service=SimpleNamespace(send_payload=send_payload),
    )

    payload = asyncio.run(
        service.send_dispatch_sr_sms(
            sr_id=100,
            intent="dispatch_follow_up",
            actor_user_id=99,
        )
    )

    assert payload["success"] is True
    assert payload["status"] == "dry_run"


def test_bluefolder_adapter_uses_closeout_matrix_for_preview(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "technician_closeout_matrix.json").write_text(
        '{"oow_hourly":{"label":"Customer Hourly","itemDescription":"Customer Hourly","billable":true,"billingStatus":"billable"}}',
        encoding="utf-8",
    )
    adapter = BlueFolderAdapter()

    preview = asyncio.run(
        adapter.preview_technician_closeout(
            TechnicianCloseoutDraft(
                sr_id=100,
                labor_code="oow_hourly",
                work_performed="Replaced failed inlet valve.",
                started_at_epoch_ms=1_000,
                ended_at_epoch_ms=5_401_000,
                signed_by="Pat Customer",
                signature_png_base64="c2lnbmF0dXJl",
                customer_approved=True,
            )
        )
    )

    assert preview.labor_label == "Customer Hourly"
    assert preview.billable is True
    assert preview.signoff_label == "Customer approved and signed by Pat Customer."


def test_bluefolder_adapter_submit_closeout_attaches_receipt(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "technician_closeout_matrix.json").write_text(
        '{"warranty":{"label":"Warranty Labor","itemDescription":"Warranty Labor","billable":false,"billingStatus":"nonbillable"}}',
        encoding="utf-8",
    )
    bluefolder_package = tmp_path / "bluefolder_api"
    bluefolder_package.mkdir()
    (bluefolder_package / "__init__.py").write_text("", encoding="utf-8")
    (bluefolder_package / "client.py").write_text(
        textwrap.dedent(
            """
            LABOR_CALLS = []
            COMMENT_CALLS = []
            ATTACHMENT_CALLS = []

            class _ServiceRequests:
                def add_labor(self, service_request_id, user_id, duration, **fields):
                    LABOR_CALLS.append((service_request_id, user_id, duration, fields))
                    return {"ok": True}

                def add_comment(self, service_request_id, comment, user_id=None, comment_is_public=False):
                    COMMENT_CALLS.append((service_request_id, comment, user_id, comment_is_public))
                    return {"ok": True}

            class _Attachments:
                def add_bytes_to_service_request(self, service_request_id, file_name, file_bytes, description="", content_type=None, is_public=False):
                    ATTACHMENT_CALLS.append((service_request_id, file_name, file_bytes, description, content_type, is_public))
                    return {"ok": True}

            class BlueFolderClient:
                def __init__(self, base_url: str | None = None):
                    self.base_url = base_url
                    self.service_requests = _ServiceRequests()
                    self.attachments = _Attachments()
            """
        ),
        encoding="utf-8",
    )
    adapter = BlueFolderAdapter(base_path=str(tmp_path), api_key="key", account_name="acme")

    result = asyncio.run(
        adapter.submit_technician_closeout(
            TechnicianCloseoutDraft(
                sr_id=100,
                labor_code="warranty",
                work_performed="Verified sealed system pressures and completed repair.",
                started_at_epoch_ms=1_000,
                ended_at_epoch_ms=3_601_000,
                signed_by="Pat Customer",
                signature_png_base64="c2lnbmF0dXJl",
                customer_approved=True,
                final_outcome="completed",
            ),
            bluefolder_user_id=9001,
        )
    )

    module = __import__("bluefolder_api.client", fromlist=["LABOR_CALLS", "ATTACHMENT_CALLS"])

    assert result["ok"] is True
    assert module.LABOR_CALLS[0][3]["billingStatus"] == "nonbillable"
    assert module.ATTACHMENT_CALLS[0][1] == "sr-100-fielddesk-closeout.txt"
    assert b"FieldDesk Closeout Receipt" in module.ATTACHMENT_CALLS[0][2]
    assert module.ATTACHMENT_CALLS[1][1] == "sr-100-customer-signature.png"
    assert module.ATTACHMENT_CALLS[1][2] == b"signature"
