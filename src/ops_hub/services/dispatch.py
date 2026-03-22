"""Dispatch service facade."""

from __future__ import annotations

from dataclasses import dataclass

from ops_hub.integrations.dispatch_adapter import DispatchAdapter
from ops_hub.models.requests import (
    BlueFolderJobSummary,
    CommandResult,
    DispatchJobSummary,
    JobLookupRequest,
    OperatorMappingRecord,
)
from ops_hub.services.bluefolder import BlueFolderService


@dataclass(slots=True)
class DispatchService:
    """Dispatch-facing orchestration service."""

    adapter: DispatchAdapter
    bluefolder_service: BlueFolderService

    async def lookup_job(self, request: JobLookupRequest) -> CommandResult:
        """Return a job lookup response using the best available read-only data."""
        if request.reference is None or not request.reference.strip():
            return await self.lookup_assignments(request)

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

    async def lookup_assignments(self, request: JobLookupRequest) -> CommandResult:
        """Return current assignments for the mapped or explicitly requested BlueFolder user."""
        target_user_id = request.target_bluefolder_user_id or request.operator_bluefolder_user_id
        if target_user_id is None:
            return CommandResult(
                message="Current assignment lookup requires a mapped BlueFolder user. Add an operator mapping first."
            )

        assignments = await self.adapter.get_assignments_for_user(target_user_id)
        origin_address = await self.adapter.get_origin_for_user(target_user_id)
        if not assignments:
            lines = [f"No current assignments were found for mapped BlueFolder user `{target_user_id}`."]
            if origin_address:
                lines.append(f"Origin: {origin_address}")
            return CommandResult(message="\n".join(lines))

        lines = [
            f"Current assignments for BlueFolder user `{target_user_id}`",
            f"Assignment count: `{len(assignments)}`",
        ]
        if origin_address:
            lines.append(f"Origin: {origin_address}")
        for assignment in assignments[:10]:
            sr_id = assignment.get("serviceRequestId") or "unknown"
            subject = assignment.get("subject") or "Unlabeled Service Request"
            city = assignment.get("city")
            state = assignment.get("state")
            start = assignment.get("start")
            route_label = assignment.get("routeLabel") or assignment.get("window") or assignment.get("timeWindow")
            location = " ".join(part for part in [city, state] if part).strip()
            detail_parts = []
            if location:
                detail_parts.append(location)
            if route_label:
                detail_parts.append(str(route_label))
            if start:
                detail_parts.append(f"start {start}")
            if detail_parts:
                lines.append(f"`SR-{sr_id}` {subject} [{' | '.join(detail_parts)}]")
            else:
                lines.append(f"`SR-{sr_id}` {subject}")

        if len(assignments) > 10:
            lines.append(f"...and {len(assignments) - 10} more assignment(s)")

        return CommandResult(message="\n".join(lines))

    async def lookup_dispatch_board(self, mappings: list[OperatorMappingRecord]) -> CommandResult:
        """Return a dispatch board summary across all mapped technicians."""
        if not mappings:
            return CommandResult(message="Dispatch board requires at least one operator mapping.")

        lines = ["Dispatch board"]
        active_techs = 0
        total_assignments = 0
        for record in mappings:
            assignments = await self.adapter.get_assignments_for_user(record.bluefolder_user_id)
            origin_address = await self.adapter.get_origin_for_user(record.bluefolder_user_id)
            assignment_count = len(assignments)
            total_assignments += assignment_count
            if assignment_count > 0:
                active_techs += 1

            summary = (
                f"Discord `{record.discord_user_id}` -> BlueFolder `{record.bluefolder_user_id}`: "
                f"`{assignment_count}` assignment(s)"
            )
            lines.append(summary)
            if origin_address:
                lines.append(f"Origin: {origin_address}")
            if assignments:
                first_assignment = assignments[0]
                sr_id = first_assignment.get("serviceRequestId") or "unknown"
                subject = first_assignment.get("subject") or "Unlabeled Service Request"
                lines.append(f"Next job: `SR-{sr_id}` {subject}")
            else:
                lines.append("Next job: none")

        lines.insert(1, f"Mapped techs: `{len(mappings)}`")
        lines.insert(2, f"Active techs: `{active_techs}`")
        lines.insert(3, f"Total visible assignments: `{total_assignments}`")
        return CommandResult(message="\n".join(lines))

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
