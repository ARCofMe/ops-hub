"""Dispatch service facade."""

from __future__ import annotations

from dataclasses import dataclass

from ops_hub.integrations.dispatch_adapter import DispatchAdapter
from ops_hub.models.requests import BlueFolderJobSummary, CommandResult, DispatchJobSummary, JobLookupRequest
from ops_hub.services.bluefolder import BlueFolderService


@dataclass(slots=True)
class DispatchService:
    """Dispatch-facing orchestration service."""

    adapter: DispatchAdapter
    bluefolder_service: BlueFolderService

    async def lookup_job(self, request: JobLookupRequest) -> CommandResult:
        """Return a job lookup response using the best available read-only data."""
        dispatch_result = await self.adapter.get_job(request.reference)
        bluefolder_result = await self.bluefolder_service.get_job_summary(request.reference)
        return CommandResult(
            message=self._format_job_message(
                request.reference,
                dispatch_result,
                bluefolder_result,
            )
        )

    def _format_job_message(
        self,
        reference: str,
        dispatch_summary: DispatchJobSummary,
        summary: BlueFolderJobSummary,
    ) -> str:
        """Build a user-facing job response from the current adapter results."""
        if summary.available and summary.integration_status == "live_read":
            lines = [
                f"Job `{reference}`",
                f"BlueFolder SR: `{summary.service_request_id or reference}`",
                f"Subject: {summary.subject or 'Unlabeled Service Request'}",
                f"Dispatch: `{dispatch_summary.integration_status}`",
            ]
            if summary.customer_id:
                lines.append(f"Customer ID: `{summary.customer_id}`")
            if summary.customer_location_id:
                lines.append(f"Location ID: `{summary.customer_location_id}`")
            lines.append(f"Dispatch detail: {dispatch_summary.message}")
            return "\n".join(lines)

        return "\n".join(
            [
                f"Job `{reference}`",
                f"BlueFolder: `{summary.integration_status}`",
                f"BlueFolder detail: {summary.message}",
                f"Dispatch: `{dispatch_summary.integration_status}`",
                f"Dispatch detail: {dispatch_summary.message}",
            ]
        )
