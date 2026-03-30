"""Dispatch service facade."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from ops_hub.integrations.dispatch_adapter import DispatchAdapter
from ops_hub.models.requests import (
    BlueFolderJobSummary,
    CommandResult,
    DispatchJobSummary,
    JobLookupRequest,
    RouteMapResult,
    TechnicianMappingRecord,
)
from ops_hub.services.bluefolder import BlueFolderService
from ops_hub.services.operator_directory import TechnicianDirectoryService
from ops_hub.services.text_blocks import section, status_section

if TYPE_CHECKING:
    from ops_hub.services.workflow_state import WorkflowStateService


@dataclass(slots=True)
class DispatchService:
    """Dispatch-facing orchestration service."""

    adapter: DispatchAdapter
    bluefolder_service: BlueFolderService
    technician_directory_service: TechnicianDirectoryService | None = None
    workflow_state_service: "WorkflowStateService | None" = None

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

        assignments = await self._assignments_for_user(target_user_id)
        origin_address = await self.adapter.get_origin_for_user(target_user_id)
        technician_label = await self._technician_label(bluefolder_user_id=target_user_id)
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
            start = self._format_assignment_time(assignment.get("start"))
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

        active_techs = 0
        total_assignments = 0
        technician_sections: list[str] = []
        for record in mappings:
            assignments = await self._assignments_for_user(record.bluefolder_user_id)
            origin_address = await self.adapter.get_origin_for_user(record.bluefolder_user_id)
            assignment_count = len(assignments)
            total_assignments += assignment_count
            if assignment_count > 0:
                active_techs += 1

            section_lines = [
                "Technician: "
                f"{await self._technician_label_for_record(record)} "
                f"| `{assignment_count}` assignment(s)"
            ]
            if origin_address:
                section_lines.append(f"Origin: {origin_address}")
            if assignments:
                first_assignment = assignments[0]
                sr_id = first_assignment.get("serviceRequestId") or "unknown"
                subject = first_assignment.get("subject") or "Unlabeled Service Request"
                section_lines.append(f"Next job: `SR-{sr_id}` {subject}")
            else:
                section_lines.append("Next job: none")
            technician_sections.append("\n".join(section_lines))

        lines = [
            "**Dispatch Board**",
            f"Mapped techs: `{len(mappings)}`",
            f"Active techs: `{active_techs}`",
            f"Total visible assignments: `{total_assignments}`",
        ]

        if self.workflow_state_service is not None:
            scanned_jobs, attention_items = await self.workflow_state_service.refresh_dispatch_attention(mappings)
            snapshot = self.workflow_state_service.current_snapshot()
            open_parts_cases = [case for case in snapshot.parts_cases if case.status == "open"]
            metrics = self.workflow_state_service.attention_metrics(snapshot)

            lines.extend(
                [
                    f"Scanned jobs: `{scanned_jobs}`",
                    f"Attention jobs: `{len(attention_items)}`",
                    f"Open parts cases: `{len(open_parts_cases)}`",
                    "",
                    "**Attention Queues**",
                ]
            )
            if metrics["stage_counts"]:
                for stage_label, count in sorted(metrics["stage_counts"].items()):
                    lines.append(f"{stage_label}: `{count}`")
            else:
                lines.append("No active attention queues.")
            if metrics["status_counts"]:
                lines.extend(["", "**Queue Status**"])
                for status, count in sorted(metrics["status_counts"].items()):
                    lines.append(f"{status}: `{count}`")
                lines.append(f"Assigned follow-up owners: `{metrics['assigned_owner_items']}`")
                lines.append(f"Unassigned follow-up owners: `{metrics['unassigned_owner_items']}`")
            if metrics["age_counts"]:
                lines.extend(["", "**Age Buckets**"])
                for bucket, count in sorted(metrics["age_counts"].items()):
                    lines.append(f"{bucket}: `{count}`")
            if metrics["urgent_open_items"] or metrics["urgent_suppressed_items"]:
                lines.extend(["", "**Urgent State**"])
                lines.append(f"Open urgent: `{metrics['urgent_open_items']}`")
                lines.append(f"Suppressed urgent: `{metrics['urgent_suppressed_items']}`")

            if attention_items:
                lines.extend(["", "**Top Attention**"])
                for item in attention_items[:8]:
                    queue_lines = [
                        f"`{item.reference}` {item.summary}",
                        f"Stage: `{item.stage_label}`",
                    ]
                    if item.age_bucket is not None and item.age_hours is not None:
                        queue_lines.append(f"Age: `{item.age_bucket}` ({item.age_hours}h)")
                    if item.location:
                        queue_lines.append(f"Location: {item.location}")
                    if item.next_action:
                        queue_lines.append(f"Next action: {item.next_action}")
                    lines.extend(["", "\n".join(queue_lines)])

            if open_parts_cases:
                lines.extend(["", "**Open Parts Cases**"])
                for case in open_parts_cases[:8]:
                    case_lines = [
                        f"`{case.reference}` `{case.stage_label}`",
                    ]
                    if case.open_request_ids:
                        case_lines.append(
                            "Tracked requests: " + ", ".join(f"`{request_id}`" for request_id in case.open_request_ids)
                        )
                    if case.age_bucket is not None and case.age_hours is not None:
                        case_lines.append(f"Age: `{case.age_bucket}` ({case.age_hours}h)")
                    if case.next_action:
                        case_lines.append(f"Next action: {case.next_action}")
                    lines.extend(["", "\n".join(case_lines)])

        lines.extend(["", "**Technician Load**"])
        for section in technician_sections:
            lines.extend(["", section])
        return CommandResult(message="\n".join(lines))

    async def lookup_dispatch_attention(
        self,
        mappings: list[TechnicianMappingRecord],
        *,
        stage_filter: str | None = None,
        technician_bluefolder_user_id: int | None = None,
        age_bucket: str | None = None,
        owner_discord_user_id: int | None = None,
    ) -> CommandResult:
        """Return a dispatcher triage view for jobs that appear actionable."""
        if not mappings:
            return CommandResult(message="Dispatch attention view requires at least one technician mapping.")

        allowed_stages = {
            "issue_reported": "Issue Reported",
            "part_received": "Received",
            "part_ready": "Ready for Scheduling",
            "quote_needed": "Quote Needed",
        }
        normalized_stage_filter = None if stage_filter is None else stage_filter.strip().lower().replace(" ", "_")
        if normalized_stage_filter is not None and normalized_stage_filter not in allowed_stages:
            return CommandResult(
                message="Dispatch attention stage filter must be one of: `issue_reported`, `part_received`, `part_ready`, `quote_needed`."
            )
        allowed_age_buckets = {"fresh", "warm", "stale", "urgent"}
        normalized_age_bucket = None if age_bucket is None else age_bucket.strip().lower().replace(" ", "_")
        if normalized_age_bucket is not None and normalized_age_bucket not in allowed_age_buckets:
            return CommandResult(
                message="Dispatch attention age filter must be one of: `fresh`, `warm`, `stale`, `urgent`."
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

        if self.workflow_state_service is not None:
            scanned_jobs, derived_attention_items = await self.workflow_state_service.refresh_dispatch_attention(
                mappings,
                stage_filter=stage_filter,
                technician_bluefolder_user_id=technician_bluefolder_user_id,
                age_bucket=normalized_age_bucket,
                owner_discord_user_id=owner_discord_user_id,
            )
            attention_items = [
                "\n".join(
                    [
                        f"`{item.reference}` {item.summary}",
                        f"Stage: `{item.stage_label}`",
                        *([f"Age: `{item.age_bucket}` ({item.age_hours}h)"] if item.age_bucket and item.age_hours is not None else []),
                        f"Technician: {await self._technician_label(bluefolder_user_id=item.owner_bluefolder_user_id)}",
                        *([f"Follow-up owner: {await self._technician_label(discord_user_id=item.assigned_owner_discord_user_id)}"] if item.assigned_owner_discord_user_id is not None else []),
                        *([f"Status: `{item.status}`"] if item.status != "open" else []),
                        *([f"Snoozed until: `{item.snoozed_until}`"] if item.snoozed_until else []),
                        *([f"Acknowledged by: {await self._technician_label(discord_user_id=item.acknowledged_by_user_id)}"] if item.acknowledged_by_user_id is not None else []),
                        *([f"Location: {item.location}"] if item.location else []),
                        *([f"Window: `{item.route_label}`"] if item.route_label else []),
                        *([f"Next action: {item.next_action}"] if item.next_action else []),
                    ]
                )
                for item in derived_attention_items
            ]
        else:
            attention_items = []
            scanned_jobs = 0
            for record in mappings:
                assignments = await self._assignments_for_user(record.bluefolder_user_id)
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
                        f"Technician: {await self._technician_label_for_record(record)}",
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
                        *([f"Age filter: `{normalized_age_bucket}`"] if normalized_age_bucket is not None else []),
                        *(
                            [
                                "Technician filter: "
                                f"{await self._technician_label(bluefolder_user_id=technician_bluefolder_user_id)}"
                            ]
                            if technician_bluefolder_user_id is not None
                            else []
                        ),
                        *(
                            [f"Owner filter: {await self._technician_label(discord_user_id=owner_discord_user_id)}"]
                            if owner_discord_user_id is not None
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
            "Actionable stages: `Issue Reported`, `Received`, `Ready for Scheduling`, `Quote Needed`",
            *(
                [f"Stage filter: `{allowed_stages[normalized_stage_filter]}`"]
                if normalized_stage_filter is not None
                else []
            ),
            *([f"Age filter: `{normalized_age_bucket}`"] if normalized_age_bucket is not None else []),
            *(
                [
                    "Technician filter: "
                    f"{await self._technician_label(bluefolder_user_id=technician_bluefolder_user_id)}"
                ]
                if technician_bluefolder_user_id is not None
                else []
            ),
            *(
                [f"Owner filter: {await self._technician_label(discord_user_id=owner_discord_user_id)}"]
                if owner_discord_user_id is not None
                else []
            ),
        ]
        for index, item in enumerate(attention_items[:20], start=1):
            lines.extend(["", f"{index}. {item}"])
        if len(attention_items) > 20:
            lines.extend(["", f"...and {len(attention_items) - 20} more attention job(s)"])
        return CommandResult(message="\n".join(lines))

    async def acknowledge_dispatch_attention(
        self,
        *,
        sr_id: int,
        stage: str | None,
        actor_user_id: int,
    ) -> CommandResult:
        """Acknowledge one workflow-backed attention item."""
        if self.workflow_state_service is None:
            return CommandResult(message="Dispatch attention actions require the workflow state service.")
        try:
            item = self.workflow_state_service.acknowledge_attention(
                sr_id=sr_id,
                stage=stage,
                actor_user_id=actor_user_id,
            )
        except ValueError as exc:
            return CommandResult(message=str(exc))
        return CommandResult(message=await self._format_attention_action_result("Acknowledged", item))

    async def snooze_dispatch_attention(
        self,
        *,
        sr_id: int,
        stage: str | None,
        hours: int,
        actor_user_id: int,
    ) -> CommandResult:
        """Snooze one workflow-backed attention item."""
        if self.workflow_state_service is None:
            return CommandResult(message="Dispatch attention actions require the workflow state service.")
        try:
            item = self.workflow_state_service.snooze_attention(
                sr_id=sr_id,
                stage=stage,
                hours=hours,
                actor_user_id=actor_user_id,
            )
        except ValueError as exc:
            return CommandResult(message=str(exc))
        return CommandResult(message=await self._format_attention_action_result("Snoozed", item))

    async def assign_dispatch_attention_owner(
        self,
        *,
        sr_id: int,
        stage: str | None,
        assigned_owner_discord_user_id: int,
        actor_user_id: int,
    ) -> CommandResult:
        """Assign an explicit follow-up owner on one attention item."""
        if self.workflow_state_service is None:
            return CommandResult(message="Dispatch attention actions require the workflow state service.")
        try:
            item = self.workflow_state_service.assign_attention_owner(
                sr_id=sr_id,
                stage=stage,
                assigned_owner_discord_user_id=assigned_owner_discord_user_id,
                actor_user_id=actor_user_id,
            )
        except ValueError as exc:
            return CommandResult(message=str(exc))
        return CommandResult(message=await self._format_attention_action_result("Assigned owner", item))

    async def clear_dispatch_attention_owner(
        self,
        *,
        sr_id: int,
        stage: str | None,
        actor_user_id: int,
    ) -> CommandResult:
        """Clear an explicit follow-up owner on one attention item."""
        if self.workflow_state_service is None:
            return CommandResult(message="Dispatch attention actions require the workflow state service.")
        try:
            item = self.workflow_state_service.clear_attention_owner(
                sr_id=sr_id,
                stage=stage,
                actor_user_id=actor_user_id,
            )
        except ValueError as exc:
            return CommandResult(message=str(exc))
        return CommandResult(message=await self._format_attention_action_result("Cleared owner", item))

    async def reopen_dispatch_attention(
        self,
        *,
        sr_id: int,
        stage: str | None,
        actor_user_id: int,
    ) -> CommandResult:
        """Reopen one workflow-backed attention item."""
        if self.workflow_state_service is None:
            return CommandResult(message="Dispatch attention actions require the workflow state service.")
        try:
            item = self.workflow_state_service.reopen_attention(
                sr_id=sr_id,
                stage=stage,
                actor_user_id=actor_user_id,
            )
        except ValueError as exc:
            return CommandResult(message=str(exc))
        return CommandResult(message=await self._format_attention_action_result("Reopened", item))

    async def unsnooze_dispatch_attention(
        self,
        *,
        sr_id: int,
        stage: str | None,
        actor_user_id: int,
    ) -> CommandResult:
        """Remove a snooze from one workflow-backed attention item."""
        if self.workflow_state_service is None:
            return CommandResult(message="Dispatch attention actions require the workflow state service.")
        try:
            item = self.workflow_state_service.unsnooze_attention(
                sr_id=sr_id,
                stage=stage,
                actor_user_id=actor_user_id,
            )
        except ValueError as exc:
            return CommandResult(message=str(exc))
        return CommandResult(message=await self._format_attention_action_result("Unsnoozed", item))

    async def describe_dispatch_attention_history(
        self,
        *,
        sr_id: int,
        stage: str | None,
    ) -> CommandResult:
        """Render recent workflow-state history for one attention item."""
        if self.workflow_state_service is None:
            return CommandResult(message="Dispatch attention history requires the workflow state service.")
        try:
            return self.workflow_state_service.describe_attention_history(sr_id=sr_id, stage=stage)
        except ValueError as exc:
            return CommandResult(message=str(exc))

    async def lookup_route_map(self, request: JobLookupRequest) -> RouteMapResult:
        """Return an inline route preview for the current technician/day."""
        target_user_id = request.target_bluefolder_user_id or request.technician_bluefolder_user_id
        if target_user_id is None:
            return RouteMapResult(
                message="Route map lookup requires a mapped BlueFolder user. Add a technician mapping first."
            )

        assignments = await self._assignments_for_user(target_user_id)
        technician_label = await self._technician_label(bluefolder_user_id=target_user_id)
        if not assignments:
            return RouteMapResult(message=f"No current assignments were found for {technician_label}.")

        stops: list[dict[str, str]] = []
        missing_address_count = 0
        for assignment in assignments[:10]:
            sr_id = assignment.get("serviceRequestId")
            if not isinstance(sr_id, str) or not sr_id.strip():
                continue
            summary = await self.bluefolder_service.get_job_summary(
                f"SR-{sr_id}",
                include_customer_contacts=False,
            )
            if not summary.available or not summary.address:
                missing_address_count += 1
                continue
            address = self._format_summary_address(summary)
            if not address:
                missing_address_count += 1
                continue
            stops.append(
                {
                    "label": f"SR-{sr_id}",
                    "address": address,
                    "subject": summary.subject or assignment.get("subject") or "Service Request",
                }
            )

        if not stops:
            return RouteMapResult(
                message=(
                    f"Current assignments were found for {technician_label}, but no mappable addresses "
                    "were available from BlueFolder."
                )
            )

        route_origin_address = self._clean_route_endpoint(request.route_origin_address)
        route_destination_address = self._clean_route_endpoint(request.route_destination_address)

        try:
            route_url, image_url = await self.adapter.build_route_map_urls(
                stops,
                origin_address=route_origin_address,
                destination_address=route_destination_address,
            )
        except TypeError:
            route_url, image_url = await self.adapter.build_route_map_urls(stops)
        lines = [
            f"**Route Map for {technician_label}**",
            f"Assignments considered: `{len(assignments)}`",
            f"Mappable stops: `{len(stops)}`",
        ]
        if len(assignments) > len(stops):
            lines.append(f"Skipped without address: `{missing_address_count}`")
        if len(assignments) > 10:
            lines.append(f"Map limited to first `{len(stops)}` of `{len(assignments)}` assignments.")
        if route_origin_address:
            lines.append(f"Custom origin: {route_origin_address}")
        if route_destination_address:
            lines.append(f"Custom destination: {route_destination_address}")

        preview_stops = stops[:8]
        for index, stop in enumerate(preview_stops, start=1):
            lines.append(f"{index}. `{stop['label']}` {stop['subject']}")
        if route_url:
            lines.extend(["", f"Open route: {route_url}"])

        return RouteMapResult(message="\n".join(lines), route_url=route_url, image_url=image_url)

    async def lookup_assignment_heatmap(
        self,
        mappings: list[TechnicianMappingRecord],
        *,
        technician_bluefolder_user_id: int | None = None,
    ) -> RouteMapResult:
        """Return a lightweight assignment heatmap across mapped technician jobs."""
        if not mappings:
            return RouteMapResult(message="Dispatch heatmap requires at least one technician mapping.")

        if technician_bluefolder_user_id is not None:
            mappings = [record for record in mappings if record.bluefolder_user_id == technician_bluefolder_user_id]
            if not mappings:
                return RouteMapResult(
                    message=(
                        "Dispatch heatmap could not find a technician mapping for "
                        f"{await self._technician_label(bluefolder_user_id=technician_bluefolder_user_id)}."
                    )
                )

        hotspot_counts: dict[str, int] = {}
        address_labels: dict[str, str] = {}
        scanned_jobs = 0
        for record in mappings:
            assignments = await self._assignments_for_user(record.bluefolder_user_id)
            for assignment in assignments[:10]:
                sr_id = assignment.get("serviceRequestId")
                if not isinstance(sr_id, str) or not sr_id.strip():
                    continue
                scanned_jobs += 1
                summary = await self.bluefolder_service.get_job_summary(
                    f"SR-{sr_id}",
                    include_customer_contacts=False,
                )
                address = self._format_summary_address(summary)
                if not summary.available or not address:
                    continue
                hotspot_counts[address] = hotspot_counts.get(address, 0) + 1
                address_labels.setdefault(address, summary.city or summary.address or address)

        if not hotspot_counts:
            return RouteMapResult(message="No mappable assignment addresses were available for the current heatmap.")

        hotspots = [
            {"address": address, "count": count}
            for address, count in sorted(hotspot_counts.items(), key=lambda item: (-item[1], item[0]))
        ]
        image_url = await self.adapter.build_heat_map_url(hotspots)

        lines = [
            "**Dispatch Heatmap**",
            f"Scanned jobs: `{scanned_jobs}`",
            f"Unique mapped locations: `{len(hotspots)}`",
        ]
        if technician_bluefolder_user_id is not None:
            lines.append(
                "Technician filter: "
                f"{await self._technician_label(bluefolder_user_id=technician_bluefolder_user_id)}"
            )
        lines.append("")
        lines.append("Top hotspots")
        for index, hotspot in enumerate(hotspots[:8], start=1):
            address = str(hotspot["address"])
            count = int(hotspot["count"])
            lines.append(f"{index}. `{count}` job(s) - {address_labels.get(address, address)}")

        return RouteMapResult(message="\n".join(lines), image_url=image_url)

    def _clean_route_endpoint(self, value: str | None) -> str | None:
        """Normalize optional custom route endpoints from command input."""
        text = (value or "").strip()
        return text or None

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
                *section("**BlueFolder**"),
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
            lines.extend(["", *section("**Dispatch**"), f"Dispatch: `{dispatch_summary.integration_status}`"])
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
            if dispatch_summary.default_origin_address:
                lines.append(f"Dispatch default origin: {dispatch_summary.default_origin_address}")
            lines.append(
                "Dispatch route tools: "
                f"route map `{'ready' if dispatch_summary.route_map_supported else 'limited'}`, "
                f"heatmap `{'ready' if dispatch_summary.heat_map_supported else 'limited'}`"
            )
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
                lines.extend(["", *section("**Context**", requestor_line)])
            lines.append("")
            lines.append(f"Dispatch detail: {dispatch_summary.message}")
            return "\n".join(lines)

        return "\n".join(
            [
                f"**Job {reference}**",
                "",
                *status_section("**BlueFolder**", status=summary.integration_status, details=summary.message),
                "",
                *status_section("**Dispatch**", status=dispatch_summary.integration_status, details=dispatch_summary.message),
                *([self._requestor_context_line(request)] if self._requestor_context_line(request) else []),
            ]
        )

    def _requestor_context_line(self, request: JobLookupRequest) -> str | None:
        """Render the resolved requestor context when available."""
        if request.technician_bluefolder_user_id is not None:
            return f"Requester: <@{request.requested_by_user_id}>"
        if request.requester_is_admin:
            return f"Requester: <@{request.requested_by_user_id}> (admin)"
        return None

    async def _technician_label_for_record(
        self,
        record: TechnicianMappingRecord,
    ) -> str:
        """Render a technician label from a mapping record."""
        return await self._technician_label(
            discord_user_id=record.discord_user_id,
            bluefolder_user_id=record.bluefolder_user_id,
        )

    async def _format_attention_action_result(self, action: str, item) -> str:
        """Render a concise response for one attention mutation."""
        lines = [
            f"**{action} Attention Item**",
            f"Reference: `{item.reference}`",
            f"Stage: `{item.stage_label}`",
            f"Status: `{item.status}`",
        ]
        if item.assigned_owner_discord_user_id is not None:
            lines.append(
                "Follow-up owner: "
                f"{await self._technician_label(discord_user_id=item.assigned_owner_discord_user_id)}"
            )
        if item.snoozed_until:
            lines.append(f"Snoozed until: `{item.snoozed_until}`")
        if item.next_action:
            lines.append(f"Next action: {item.next_action}")
        return "\n".join(lines)

    async def _technician_label(
        self,
        *,
        discord_user_id: int | None = None,
        bluefolder_user_id: int | None = None,
    ) -> str:
        """Render the best available technician label for dispatch messages."""
        if discord_user_id is None and bluefolder_user_id is not None and self.technician_directory_service is not None:
            discord_user_id = self.technician_directory_service.reverse_mappings().get(bluefolder_user_id)
        if discord_user_id is not None and self.technician_directory_service is not None:
            return self.technician_directory_service.discord_mention(discord_user_id)
        if discord_user_id is not None:
            return f"<@{discord_user_id}>"
        if bluefolder_user_id is not None:
            user_name = await self.bluefolder_service.get_user_name(bluefolder_user_id)
            if user_name:
                return user_name
            return f"BlueFolder user `{bluefolder_user_id}`"
        return "Unknown technician"

    async def _assignments_for_user(self, bluefolder_user_id: int) -> list[dict[str, str | bool | None]]:
        """Load current assignments, preferring direct BlueFolder reads with a wrapper fallback."""
        assignments = await self.bluefolder_service.get_assignments_for_user_today(bluefolder_user_id)
        if assignments:
            return assignments
        return await self.adapter.get_assignments_for_user(bluefolder_user_id)

    def _format_assignment_time(self, value: str | bool | None) -> str | None:
        """Render BlueFolder assignment timestamps in a compact human-readable form."""
        if not isinstance(value, str) or not value.strip():
            return None

        text = value.strip()
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%H:%M"):
            try:
                return datetime.strptime(text, fmt).strftime("%I:%M %p").lstrip("0")
            except ValueError:
                continue
        return text

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

    def _format_summary_address(self, summary: BlueFolderJobSummary) -> str | None:
        """Render a single-line service-request address for route mapping."""
        if not summary.address:
            return None
        trailing = " ".join(
            part for part in [summary.city, summary.state, summary.postal_code] if part
        ).strip()
        return ", ".join(part for part in [summary.address, trailing] if part)
