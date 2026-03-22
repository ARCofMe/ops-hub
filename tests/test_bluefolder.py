"""BlueFolder adapter and service tests for Ops Hub."""

import asyncio
from pathlib import Path

from ops_hub.integrations.bluefolder_adapter import BlueFolderAdapter
from ops_hub.models.requests import JobLookupRequest
from ops_hub.services.bluefolder import BlueFolderService
from ops_hub.services.dispatch import DispatchService
from ops_hub.integrations.dispatch_adapter import DispatchAdapter


class DummyDispatchAdapter(DispatchAdapter):
    """Dispatch adapter test double."""

    async def get_job(self, reference: str) -> dict[str, str]:
        return {
            "reference": reference,
            "status": "placeholder",
            "source": "dispatch_adapter",
        }


def test_bluefolder_adapter_reports_unconfigured_status() -> None:
    adapter = BlueFolderAdapter(base_path=None)

    result = asyncio.run(adapter.get_job_summary("SR-100"))

    assert result.integration_status == "unconfigured"
    assert result.available is False


def test_bluefolder_adapter_reports_ready_status_for_existing_path(tmp_path: Path) -> None:
    adapter = BlueFolderAdapter(base_path=str(tmp_path))

    result = asyncio.run(adapter.get_job_summary("SR-100"))

    assert result.integration_status == "placeholder_ready"
    assert result.available is True
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

    assert "BlueFolder status: placeholder_ready." in result.message
    assert "Read-only wrapper not implemented yet." in result.message
