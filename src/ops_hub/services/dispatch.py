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
        bluefolder_result = await self.bluefolder_service.get_job_summary(request.reference)
        dispatch_result = await self.adapter.get_job(
            request.reference,
            bluefolder_result,
            request.operator_bluefolder_user_id,
        )
        return CommandResult(
            message=self._format_job_message(
                request,
                request.reference,
                dispatch_result,
                bluefolder_result,
            )
        )

    def _format_job_message(
        self,
        request: JobLookupRequest,
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
            if summary.address:
                location = summary.address
                if summary.city or summary.state or summary.postal_code:
                    location = ", ".join(
                        part
                        for part in [
                            summary.address,
                            " ".join(part for part in [summary.city, summary.state, summary.postal_code] if part).strip(),
                        ]
                        if part
                    )
                lines.append(f"Address: {location}")
            if dispatch_summary.stop_label:
                lines.append(f"Dispatch stop: `{dispatch_summary.stop_label}`")
            if dispatch_summary.stop_window:
                lines.append(f"Dispatch window: `{dispatch_summary.stop_window}`")
            if dispatch_summary.stop_address:
                lines.append(f"Dispatch stop address: {dispatch_summary.stop_address}")
            if dispatch_summary.technician_assignment_status:
                lines.append(f"Technician assignment: `{dispatch_summary.technician_assignment_status}`")
            if dispatch_summary.technician_origin_address:
                lines.append(f"Technician origin: {dispatch_summary.technician_origin_address}")
            if requestor_line := self._requestor_context_line(request):
                lines.append(requestor_line)
            lines.append(f"Dispatch detail: {dispatch_summary.message}")
            return "\n".join(lines)

        return "\n".join(
            [
                f"Job `{reference}`",
                f"BlueFolder: `{summary.integration_status}`",
                f"BlueFolder detail: {summary.message}",
                f"Dispatch: `{dispatch_summary.integration_status}`",
                *([self._requestor_context_line(request)] if self._requestor_context_line(request) else []),
                f"Dispatch detail: {dispatch_summary.message}",
            ]
        )

    def _requestor_context_line(self, request: JobLookupRequest) -> str | None:
        """Render the resolved requestor context when available."""
        if request.operator_bluefolder_user_id is not None:
            return f"Requester mapping: BlueFolder user `{request.operator_bluefolder_user_id}`"
        if request.requester_is_admin:
            return "Requester mapping: admin access"
        return None
