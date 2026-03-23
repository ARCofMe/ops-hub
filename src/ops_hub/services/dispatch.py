"""Dispatch service facade."""

from __future__ import annotations

from dataclasses import dataclass

from ops_hub.integrations.dispatch_adapter import DispatchAdapter
from ops_hub.models.requests import (
    BlueFolderJobSummary,
    CommandResult,
    DispatchJobSummary,
    JobLookupRequest,
    TechnicianMappingRecord,
)
from ops_hub.services.bluefolder import BlueFolderService
from ops_hub.services.operator_directory import TechnicianDirectoryService


@dataclass(slots=True)
class DispatchService:
    """Dispatch-facing orchestration service."""

    adapter: DispatchAdapter
    bluefolder_service: BlueFolderService
    technician_directory_service: TechnicianDirectoryService | None = None

    async def lookup_job(self, request: JobLookupRequest) -> CommandResult:
        """Return a job lookup response using the best available read-only data."""
        if request.reference is None or not request.reference.strip():
            return await self.lookup_assignments(request)

        bluefolder_result = await self.bluefolder_service.get_job_summary(request.reference)
        parts_brief = None
        if bluefolder_result.available and bluefolder_result.service_request_id:
            try:
                parts_brief = await self.bluefolder_service.get_parts_brief(int(bluefolder_result.service_request_id))
            except ValueError:
                parts_brief = None
        dispatch_result = await self.adapter.get_job(
            request.reference,
            bluefolder_result,
            request.technician_bluefolder_user_id,
        )
        return CommandResult(
            message=self._format_job_message(
                request,
                request.reference,
                dispatch_result,
                bluefolder_result,
                parts_brief,
            )
        )

    async def lookup_assignments(self, request: JobLookupRequest) -> CommandResult:
        """Return current assignments for the mapped or explicitly requested BlueFolder user."""
        target_user_id = request.target_bluefolder_user_id or request.technician_bluefolder_user_id
        if target_user_id is None:
            return CommandResult(
                message="Current assignment lookup requires a mapped BlueFolder user. Add a technician mapping first."
            )

        assignments = await self.adapter.get_assignments_for_user(target_user_id)
        origin_address = await self.adapter.get_origin_for_user(target_user_id)
        technician_label = self._technician_label(bluefolder_user_id=target_user_id)
        if not assignments:
            lines = [f"No current assignments were found for {technician_label}."]
            if origin_address:
                lines.append(f"Origin: {origin_address}")
            return CommandResult(message="\n".join(lines))

        lines = [
            f"Current assignments for {technician_label}",
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

    async def lookup_dispatch_board(self, mappings: list[TechnicianMappingRecord]) -> CommandResult:
        """Return a dispatch board summary across all mapped technicians."""
        if not mappings:
            return CommandResult(message="Dispatch board requires at least one technician mapping.")

        lines = ["**Dispatch Board**"]
        active_techs = 0
        total_assignments = 0
        for record in mappings:
            assignments = await self.adapter.get_assignments_for_user(record.bluefolder_user_id)
            origin_address = await self.adapter.get_origin_for_user(record.bluefolder_user_id)
            assignment_count = len(assignments)
            total_assignments += assignment_count
            if assignment_count > 0:
                active_techs += 1

            summary = f"Technician: {self._technician_label_for_record(record)} | `{assignment_count}` assignment(s)"
            lines.extend(["", summary])
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

    async def lookup_dispatch_attention(
        self,
        mappings: list[TechnicianMappingRecord],
        *,
        stage_filter: str | None = None,
        technician_bluefolder_user_id: int | None = None,
    ) -> CommandResult:
        """Return a dispatcher triage view for jobs that appear actionable."""
        if not mappings:
            return CommandResult(message="Dispatch attention view requires at least one technician mapping.")

        allowed_stages = {
            "issue_reported": "Issue Reported",
            "part_received": "Received",
            "part_ready": "Ready for Scheduling",
        }
        normalized_stage_filter = None if stage_filter is None else stage_filter.strip().lower().replace(" ", "_")
        if normalized_stage_filter is not None and normalized_stage_filter not in allowed_stages:
            return CommandResult(
                message="Dispatch attention stage filter must be one of: `issue_reported`, `part_received`, `part_ready`."
            )

        if technician_bluefolder_user_id is not None:
            mappings = [
                record for record in mappings if record.bluefolder_user_id == technician_bluefolder_user_id
            ]
            if not mappings:
                return CommandResult(
                    message=(
                        "Dispatch attention view could not find a technician mapping for "
                        f"{self._technician_label(bluefolder_user_id=technician_bluefolder_user_id)}."
                    )
                )

        attention_items: list[str] = []
        scanned_jobs = 0
        for record in mappings:
            assignments = await self.adapter.get_assignments_for_user(record.bluefolder_user_id)
            for assignment in assignments[:10]:
                sr_id = assignment.get("serviceRequestId")
                if sr_id in (None, ""):
                    continue
                scanned_jobs += 1
                try:
                    snapshot = await self.bluefolder_service.get_parts_snapshot(int(str(sr_id)))
                except ValueError:
                    continue
                if snapshot is None:
                    continue
                if snapshot.stage not in allowed_stages:
                    continue
                if normalized_stage_filter is not None and snapshot.stage != normalized_stage_filter:
                    continue

                subject = assignment.get("subject") or "Unlabeled Service Request"
                route_label = assignment.get("routeLabel") or assignment.get("window") or assignment.get("timeWindow")
                location = " ".join(
                    part for part in [assignment.get("city"), assignment.get("state")] if part
                ).strip()
                item_lines = [
                    f"`SR-{sr_id}` {subject}",
                    f"Stage: `{snapshot.stage_label}`",
                    f"Technician: {self._technician_label_for_record(record)}",
                ]
                if location:
                    item_lines.append(f"Location: {location}")
                if route_label:
                    item_lines.append(f"Window: `{route_label}`")
                attention_items.append("\n".join(item_lines))

        if not attention_items:
            return CommandResult(
                message="\n".join(
                    [
                        "**Dispatch Attention**",
                        f"Scanned jobs: `{scanned_jobs}`",
                        *(
                            [f"Stage filter: `{allowed_stages[normalized_stage_filter]}`"]
                            if normalized_stage_filter is not None
                            else []
                        ),
                        *(
                            [f"Technician filter: {self._technician_label(bluefolder_user_id=technician_bluefolder_user_id)}"]
                            if technician_bluefolder_user_id is not None
                            else []
                        ),
                        "No mapped assignments currently match the parts-attention stages.",
                    ]
                )
            )

        lines = [
            "**Dispatch Attention**",
            f"Scanned jobs: `{scanned_jobs}`",
            f"Attention jobs: `{len(attention_items)}`",
            "Actionable stages: `Issue Reported`, `Received`, `Ready for Scheduling`",
            *(
                [f"Stage filter: `{allowed_stages[normalized_stage_filter]}`"]
                if normalized_stage_filter is not None
                else []
            ),
            *(
                [f"Technician filter: {self._technician_label(bluefolder_user_id=technician_bluefolder_user_id)}"]
                if technician_bluefolder_user_id is not None
                else []
            ),
        ]
        for index, item in enumerate(attention_items[:20], start=1):
            lines.extend(["", f"{index}. {item}"])
        if len(attention_items) > 20:
            lines.extend(["", f"...and {len(attention_items) - 20} more attention job(s)"])
        return CommandResult(message="\n".join(lines))

    def _format_job_message(
        self,
        request: JobLookupRequest,
        reference: str,
        dispatch_summary: DispatchJobSummary,
        summary: BlueFolderJobSummary,
        parts_brief: CommandResult | None = None,
    ) -> str:
        """Build a user-facing job response from the current adapter results."""
        if summary.available and summary.integration_status == "live_read":
            lines = [
                f"**Job {reference}**",
                f"Subject: {summary.subject or 'Unlabeled Service Request'}",
                "",
                "**BlueFolder**",
                f"BlueFolder SR: `{summary.service_request_id or reference}`",
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
            lines.extend(["", "**Dispatch**", f"Dispatch: `{dispatch_summary.integration_status}`"])
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
            if parts_lines := self._parts_context_lines(parts_brief):
                lines.extend(["", "**Parts**"])
                lines.extend(parts_lines)
            if parts_brief is not None:
                for line in parts_brief.message.splitlines():
                    if line.startswith("Recommended next action:"):
                        lines.append("")
                        lines.append(line)
                        break
            if requestor_line := self._requestor_context_line(request):
                lines.extend(["", "**Context**"])
                lines.append(requestor_line)
            lines.append("")
            lines.append(f"Dispatch detail: {dispatch_summary.message}")
            return "\n".join(lines)

        return "\n".join(
            [
                f"**Job {reference}**",
                "",
                "**BlueFolder**",
                f"Status: `{summary.integration_status}`",
                f"BlueFolder detail: {summary.message}",
                "",
                "**Dispatch**",
                f"Status: `{dispatch_summary.integration_status}`",
                *([self._requestor_context_line(request)] if self._requestor_context_line(request) else []),
                f"Dispatch detail: {dispatch_summary.message}",
            ]
        )

    def _requestor_context_line(self, request: JobLookupRequest) -> str | None:
        """Render the resolved requestor context when available."""
        if request.technician_bluefolder_user_id is not None:
            return (
                "Requester: "
                f"{self._technician_label(discord_user_id=request.requested_by_user_id, bluefolder_user_id=request.technician_bluefolder_user_id)}"
            )
        if request.requester_is_admin:
            return f"Requester: <@{request.requested_by_user_id}> (admin)"
        return None

    def _technician_label_for_record(self, record: TechnicianMappingRecord) -> str:
        """Render a technician label from a mapping record."""
        return self._technician_label(
            discord_user_id=record.discord_user_id,
            bluefolder_user_id=record.bluefolder_user_id,
        )

    def _technician_label(
        self,
        *,
        discord_user_id: int | None = None,
        bluefolder_user_id: int | None = None,
    ) -> str:
        """Render the best available technician label for dispatch messages."""
        if self.technician_directory_service is not None:
            return self.technician_directory_service.technician_label(
                discord_user_id=discord_user_id,
                bluefolder_user_id=bluefolder_user_id,
            )
        if discord_user_id is not None and bluefolder_user_id is not None:
            return f"<@{discord_user_id}> (BlueFolder `{bluefolder_user_id}`)"
        if discord_user_id is not None:
            return f"<@{discord_user_id}>"
        if bluefolder_user_id is not None:
            return f"BlueFolder user `{bluefolder_user_id}`"
        return "Unknown technician"

    def _parts_context_lines(self, parts_brief: CommandResult | None) -> list[str]:
        """Extract a compact parts snapshot from the BlueFolder parts brief."""
        if parts_brief is None:
            return []

        stage_line = None
        status_line = None
        issue_line = None
        for line in parts_brief.message.splitlines():
            if line.startswith("Parts stage:"):
                stage_line = line.replace("Parts stage:", "Parts:")
            elif line.startswith("Status detail:"):
                status_line = line
            elif line.startswith("Issue detail:"):
                issue_line = line

        result = []
        if stage_line:
            result.append(stage_line)
        if status_line:
            result.append(status_line)
        elif issue_line:
            result.append(issue_line)
        return result
