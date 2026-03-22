"""BlueFolder adapter and service tests for Ops Hub."""

import asyncio
from pathlib import Path
import textwrap

from ops_hub.integrations.bluefolder_adapter import BlueFolderAdapter
from ops_hub.integrations.dispatch_adapter import DispatchAdapter
from ops_hub.models.requests import JobLookupRequest
from ops_hub.services.bluefolder import BlueFolderService
from ops_hub.services.dispatch import DispatchService


class DummyDispatchAdapter(DispatchAdapter):
    """Dispatch adapter test double."""

    async def get_job(self, reference: str, bluefolder_summary=None):
        return await super().get_job(reference, bluefolder_summary)


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

    assert "BlueFolder: `import_error`" in result.message
    assert "Failed to import bluefolder_api from configured path" in result.message
    assert "Dispatch: `unconfigured`" in result.message


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
                operator_bluefolder_user_id=13051,
            )
        )
    )

    assert "Job `SR-100`" in result.message
    assert "BlueFolder SR: `100`" in result.message
    assert "Subject: SR description 100" in result.message
    assert "Dispatch: `stop_preview`" in result.message
    assert "Customer ID: `42`" in result.message
    assert "Location ID: `9`" in result.message
    assert "Address: 123 Main St, Portland ME 04101" in result.message
    assert "Dispatch stop: `SR-100`" in result.message
    assert "Dispatch window: `ALL_DAY`" in result.message
    assert "Dispatch stop address: 123 Main St, Portland, ME 04101" in result.message
    assert "Requester mapping: BlueFolder user `13051`" in result.message
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
    assert "BlueFolder SR `100`: SR description 100" == result.message


def test_bluefolder_adapter_rejects_non_numeric_reference(tmp_path: Path) -> None:
    adapter = BlueFolderAdapter(base_path=str(tmp_path), api_key="key", account_name="acme")

    result = asyncio.run(adapter.get_job_summary("ticket-alpha"))

    assert result.integration_status == "unsupported_reference"
    assert result.available is False
