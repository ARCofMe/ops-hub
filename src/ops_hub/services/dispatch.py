"""Dispatch service facade."""

from __future__ import annotations

from dataclasses import dataclass

from ops_hub.integrations.dispatch_adapter import DispatchAdapter
from ops_hub.models.requests import CommandResult, JobLookupRequest
from ops_hub.services.bluefolder import BlueFolderService


@dataclass(slots=True)
class DispatchService:
    """Dispatch-facing orchestration service."""

    adapter: DispatchAdapter
    bluefolder_service: BlueFolderService

    async def lookup_job(self, request: JobLookupRequest) -> CommandResult:
        """Return a placeholder job lookup response."""
        # TODO: Start by combining read-only BlueFolder lookups with dispatch wrappers.
        dispatch_result = await self.adapter.get_job(request.reference)
        bluefolder_result = await self.bluefolder_service.get_job_summary(request.reference)
        return CommandResult(
            message=(
                f"Job lookup placeholder for `{request.reference}`. "
                f"Dispatch source: {dispatch_result['source']}; "
                f"BlueFolder status: {bluefolder_result.integration_status}. "
                f"{bluefolder_result.message}"
            )
        )
