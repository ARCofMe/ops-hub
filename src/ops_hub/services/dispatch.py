"""Dispatch service facade."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime
import logging
from pathlib import Path
import pickle
import sqlite3
import threading
import time
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
from ops_hub.services.bluefolder_status_catalog import describe_service_request_status
from ops_hub.services.bluefolder import BlueFolderService
from ops_hub.services.operator_directory import TechnicianDirectoryService
from ops_hub.services.sms import DispatchSmsService
from ops_hub.services.text_blocks import section, status_section

if TYPE_CHECKING:
    from ops_hub.services.workflow_state import WorkflowStateService


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DispatchService:
    """Dispatch-facing orchestration service."""

    adapter: DispatchAdapter
    bluefolder_service: BlueFolderService
    technician_directory_service: TechnicianDirectoryService | None = None
    workflow_state_service: "WorkflowStateService | None" = None
    sms_service: DispatchSmsService | None = None
    board_snapshot_ttl_seconds: float = 30.0
    attention_refresh_timeout_seconds: float = 18.0
    discovery_scan_timeout_seconds: float = 8.0
    assignment_cache_ttl_seconds: float = 120.0
    job_summary_cache_ttl_seconds: float = 300.0
    sr_payload_cache_ttl_seconds: float = 180.0
    route_payload_cache_ttl_seconds: float = 180.0
    heatmap_payload_cache_ttl_seconds: float = 180.0
    persistent_cache_path: Path | None = None
    persistent_cache_stale_ttl_seconds: float = 3600.0
    _board_refresh_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _board_refresh_running: bool = field(default=False, init=False, repr=False)
    _cache_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _cache_entries: dict[str, tuple[float, object]] = field(default_factory=dict, init=False, repr=False)
    _inflight_tasks: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Task]] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _persistent_cache_ready: bool = field(default=False, init=False, repr=False)

    async def lookup_job(self, request: JobLookupRequest) -> CommandResult:
        """Return a job lookup response using the best available read-only data."""
        if request.reference is None or not request.reference.strip():
            return await self.lookup_assignments(request)

        bluefolder_result = await self._bluefolder_job_summary(request.reference)
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
            "new_sr_triage": "New SR Triage",
            "model_serial_needed": "Model/Serial Needed",
            "likely_parts_previsit": "Likely Parts Previsit",
            "diagnostic_required": "Diagnostic Required",
            "previsit_quote_needed": "Previsit Quote Needed",
            "issue_reported": "Issue Reported",
            "part_received": "Received",
            "part_ready": "Ready for Scheduling",
            "quote_needed": "Quote Needed",
        }
        normalized_stage_filter = None if stage_filter is None else stage_filter.strip().lower().replace(" ", "_")
        if normalized_stage_filter is not None and normalized_stage_filter not in allowed_stages:
            return CommandResult(
                message=(
                    "Dispatch attention stage filter must be one of: "
                    "`new_sr_triage`, `model_serial_needed`, `likely_parts_previsit`, "
                    "`diagnostic_required`, `previsit_quote_needed`, "
                    "`issue_reported`, `part_received`, `part_ready`, `quote_needed`."
                )
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
                        *(
                            [
                                f"Follow-up owner: {await self._technician_label(discord_user_id=item.assigned_owner_discord_user_id, bluefolder_user_id=item.assigned_owner_bluefolder_user_id)}"
                            ]
                            if item.assigned_owner_bluefolder_user_id is not None or item.assigned_owner_discord_user_id is not None
                            else []
                        ),
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
                        f"Technician: {await self._technician_label(bluefolder_user_id=record.bluefolder_user_id)}",
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
            (
                "Actionable stages: `New SR Triage`, `Model/Serial Needed`, `Likely Parts Previsit`, "
                "`Diagnostic Required`, `Previsit Quote Needed`, `Issue Reported`, `Received`, "
                "`Ready for Scheduling`, `Quote Needed`"
            ),
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
        assigned_owner_bluefolder_user_id: int | None = None,
        assigned_owner_discord_user_id: int | None = None,
        actor_user_id: int,
    ) -> CommandResult:
        """Assign an explicit follow-up owner on one attention item."""
        if self.workflow_state_service is None:
            return CommandResult(message="Dispatch attention actions require the workflow state service.")
        resolved_bluefolder_user_id = assigned_owner_bluefolder_user_id
        if resolved_bluefolder_user_id is None:
            resolved_bluefolder_user_id = self._bluefolder_user_id_for_discord_user_id(assigned_owner_discord_user_id)
        if resolved_bluefolder_user_id is None and assigned_owner_discord_user_id is not None:
            resolved_bluefolder_user_id = assigned_owner_discord_user_id
        if resolved_bluefolder_user_id is None or resolved_bluefolder_user_id <= 0:
            return CommandResult(message="Dispatch attention owner assignment requires a positive BlueFolder user id.")
        try:
            item = self.workflow_state_service.assign_attention_owner(
                sr_id=sr_id,
                stage=stage,
                assigned_owner_bluefolder_user_id=resolved_bluefolder_user_id,
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

    async def set_dispatch_triage_disposition(
        self,
        *,
        sr_id: int,
        disposition: str,
        actor_user_id: int,
        details: str | None = None,
    ) -> CommandResult:
        """Record one triage disposition decision for a service request."""
        if self.workflow_state_service is None:
            return CommandResult(message="Dispatch triage actions require the workflow state service.")
        try:
            item = self.workflow_state_service.set_triage_disposition(
                sr_id=sr_id,
                disposition=disposition,
                actor_user_id=actor_user_id,
                details=details,
            )
        except ValueError as exc:
            return CommandResult(message=str(exc))
        if item is None:
            return CommandResult(
                message="\n".join(
                    [
                        f"**Triage Disposition SR-{sr_id}**",
                        "Disposition: `schedule_normal`",
                        "Triage queue cleared. Dispatch can schedule the SR normally.",
                        *( [f"Detail: {details}"] if details else [] ),
                    ]
                )
            )
        return CommandResult(message=await self._format_attention_action_result("Triage disposition set", item))

    async def get_dispatch_board_payload(self) -> dict[str, object]:
        """Return a structured dispatch board payload for frontend clients."""
        started_at = time.perf_counter()
        all_records = await self._dispatch_operator_records()
        mappings = [record for record in all_records if self._is_dispatch_board_candidate(record)]
        if not all_records:
            return {
                "mappedTechs": 0,
                "visibleOperators": 0,
                "discordLinkedTechs": 0,
                "activeTechs": 0,
                "totalVisibleAssignments": 0,
                "scannedJobs": 0,
                "attentionJobs": 0,
                "openPartsCases": 0,
                "attentionMetrics": {},
                "topAttention": [],
                "openPartsCaseItems": [],
                "technicianLoad": [],
            }
        if not mappings:
            return {
                "mappedTechs": 0,
                "visibleOperators": len(all_records),
                "discordLinkedTechs": 0,
                "activeTechs": 0,
                "totalVisibleAssignments": 0,
                "scannedJobs": 0,
                "attentionJobs": 0,
                "openPartsCases": 0,
                "attentionMetrics": {},
                "topAttention": [],
                "openPartsCaseItems": [],
                "technicianLoad": [],
            }

        technician_load_started_at = time.perf_counter()
        technician_load = await asyncio.gather(
            *(self._dispatch_board_technician_entry(record) for record in mappings)
        )
        technician_load_duration_ms = int((time.perf_counter() - technician_load_started_at) * 1000)
        active_techs = sum(1 for entry in technician_load if entry["hasAssignments"])
        total_assignments = sum(int(entry["assignmentCount"]) for entry in technician_load)

        scanned_jobs = 0
        attention_items = []
        open_parts_cases: list[dict[str, object]] = []
        metrics: dict[str, object] = {}
        workflow_refresh_duration_ms = 0
        payload_shape_duration_ms = 0
        if self.workflow_state_service is not None:
            snapshot = self.workflow_state_service.current_snapshot()
            if self._board_snapshot_exists(snapshot):
                current_attention_items = list(snapshot.attention_items)
                scanned_jobs = self._estimate_scanned_jobs(snapshot)
                self._ensure_board_refresh(mappings)
            else:
                current_attention_items = []
                scanned_jobs = 0
                self._ensure_board_refresh(mappings)
            payload_shape_started_at = time.perf_counter()
            attention_items = list(await asyncio.gather(*(self._attention_item_payload(item) for item in current_attention_items)))
            open_parts_cases = list(
                await asyncio.gather(
                    *(self._parts_case_payload(case) for case in snapshot.parts_cases if case.status == "open")
                )
            )
            metrics = self.workflow_state_service.attention_metrics(snapshot)
            payload_shape_duration_ms = int((time.perf_counter() - payload_shape_started_at) * 1000)

        total_duration_ms = int((time.perf_counter() - started_at) * 1000)
        logger.info(
            "Dispatch board payload built",
            extra={
                "mapped_techs": len(mappings),
                "visible_operators": len(all_records),
                "visible_assignments": total_assignments,
                "scanned_jobs": scanned_jobs,
                "attention_jobs": len(attention_items),
                "duration_ms": total_duration_ms,
                "technician_load_ms": technician_load_duration_ms,
                "workflow_refresh_ms": workflow_refresh_duration_ms,
                "payload_shape_ms": payload_shape_duration_ms,
            },
        )

        return {
            "mappedTechs": len(mappings),
            "visibleOperators": len(all_records),
            "discordLinkedTechs": sum(1 for record in mappings if record.discord_user_id is not None),
            "activeTechs": active_techs,
            "totalVisibleAssignments": total_assignments,
            "scannedJobs": scanned_jobs,
            "attentionJobs": len(attention_items),
            "openPartsCases": len(open_parts_cases),
            "attentionMetrics": metrics,
            "topAttention": attention_items[:8],
            "openPartsCaseItems": open_parts_cases[:8],
            "technicianLoad": technician_load,
        }

    def _board_snapshot_exists(self, snapshot) -> bool:
        """Return whether any persisted workflow snapshot is available for board rendering."""
        return bool(getattr(snapshot, "updated_at", None))

    def _board_snapshot_is_usable(self, snapshot) -> bool:
        """Return whether the board can render from the persisted workflow snapshot."""
        updated_at = getattr(snapshot, "updated_at", None)
        if not updated_at:
            return False
        try:
            updated = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
        except ValueError:
            return False
        now = datetime.now(updated.tzinfo) if updated.tzinfo is not None else datetime.now()
        return (now - updated).total_seconds() <= self.board_snapshot_ttl_seconds

    def _estimate_scanned_jobs(self, snapshot) -> int:
        """Best-effort scanned job estimate from the current workflow snapshot."""
        references = {item.reference for item in snapshot.attention_items if item.reference}
        references.update(case.reference for case in snapshot.parts_cases if case.reference)
        return len(references)

    def _ensure_board_refresh(self, mappings: list[TechnicianMappingRecord]) -> None:
        """Run one background workflow refresh so the next board request is warm."""
        with self._board_refresh_lock:
            if self._board_refresh_running or self.workflow_state_service is None:
                return
            self._board_refresh_running = True

        async def _refresh_and_warm() -> None:
            await self.workflow_state_service.refresh_dispatch_attention(mappings)
            sr_ids = self._board_snapshot_sr_ids(self.workflow_state_service.current_snapshot())
            if sr_ids and hasattr(self.workflow_state_service, "warm_photo_compliance_for_sr_ids"):
                warmed = await self.workflow_state_service.warm_photo_compliance_for_sr_ids(sr_ids)
                logger.info(
                    "Board photo compliance warmed",
                    extra={"sr_count": len(sr_ids), "refreshed_count": warmed},
                )

        def _runner() -> None:
            try:
                asyncio.run(_refresh_and_warm())
            except Exception:
                logger.exception("Background board refresh failed")
            finally:
                with self._board_refresh_lock:
                    self._board_refresh_running = False

        threading.Thread(target=_runner, name="ops-hub-board-refresh", daemon=True).start()

    @staticmethod
    def _board_snapshot_sr_ids(snapshot) -> list[int]:
        """Collect unique SR ids represented in the current board snapshot."""
        sr_ids: list[int] = []
        seen: set[int] = set()
        for item in getattr(snapshot, "attention_items", []):
            sr_id = int(getattr(item, "sr_id", 0) or 0)
            if sr_id > 0 and sr_id not in seen:
                seen.add(sr_id)
                sr_ids.append(sr_id)
        for case in getattr(snapshot, "parts_cases", []):
            sr_id = int(getattr(case, "sr_id", 0) or 0)
            if sr_id > 0 and sr_id not in seen:
                seen.add(sr_id)
                sr_ids.append(sr_id)
        return sr_ids

    async def _dispatch_board_technician_entry(self, record: TechnicianMappingRecord) -> dict[str, object]:
        """Build one dispatch-board technician row without blocking the rest of the board."""
        assignments_task = asyncio.create_task(self._dispatch_board_assignments(record.bluefolder_user_id))
        origin_task = asyncio.create_task(self._dispatch_board_origin(record.bluefolder_user_id))
        label_task = asyncio.create_task(self._board_technician_label_for_record(record))
        assignments, origin_address, technician_label = await asyncio.gather(
            assignments_task,
            origin_task,
            label_task,
        )
        assignment_count = len(assignments)
        first_assignment = assignments[0] if assignments else None
        return {
            "discordUserId": record.discord_user_id,
            "bluefolderUserId": record.bluefolder_user_id,
            "technicianLabel": technician_label,
            "bluefolderUserType": record.bluefolder_user_type,
            "bluefolderRole": record.bluefolder_role,
            "assignmentCount": assignment_count,
            "hasAssignments": assignment_count > 0,
            "originAddress": origin_address,
            "nextJob": (
                {
                    "srId": str(first_assignment.get("serviceRequestId") or ""),
                    "summary": str(first_assignment.get("subject") or "Unlabeled Service Request"),
                }
                if first_assignment is not None
                else None
            ),
        }

    async def _dispatch_board_assignments(self, bluefolder_user_id: int) -> list[dict[str, str | bool | None]]:
        """Load board assignments for one mapped technician with graceful degradation."""
        try:
            return await self._assignments_for_user(bluefolder_user_id, include_subjects=False)
        except Exception as exc:
            logger.warning(
                "Dispatch board assignments unavailable for mapped BlueFolder user %s: %s",
                bluefolder_user_id,
                exc,
            )
            return []

    async def _dispatch_board_origin(self, bluefolder_user_id: int) -> str | None:
        """Load board origin context for one mapped technician with graceful degradation."""
        try:
            return await self.adapter.get_origin_for_user(bluefolder_user_id)
        except Exception as exc:
            logger.warning(
                "Dispatch board origin unavailable for mapped BlueFolder user %s: %s",
                bluefolder_user_id,
                exc,
            )
            return None

    async def get_dispatch_attention_payload(
        self,
        *,
        stage: str | None = None,
        age: str | None = None,
        technician_bluefolder_user_id: int | None = None,
        owner_discord_user_id: int | None = None,
        status: str | None = None,
        reference: str | None = None,
    ) -> dict[str, object]:
        """Return structured attention queue payload for frontend clients."""
        mappings = await self._dispatch_operator_records()
        routeable_mappings = [record for record in mappings if self._is_dispatch_board_candidate(record)]
        if self.workflow_state_service is None:
            return {
                "scannedJobs": 0,
                "filters": {
                    "stage": stage,
                    "age": age,
                    "technicianBluefolderUserId": technician_bluefolder_user_id,
                    "ownerDiscordUserId": owner_discord_user_id,
                    "status": status,
                    "reference": reference,
                },
                "items": [],
            }
        snapshot = self.workflow_state_service.current_snapshot()
        if self._board_snapshot_exists(snapshot):
            scanned_jobs = self._estimate_scanned_jobs(snapshot)
            items = list(getattr(snapshot, "attention_items", []))
            self._ensure_board_refresh(routeable_mappings)
        else:
            try:
                scanned_jobs, items = await asyncio.wait_for(
                    self.workflow_state_service.refresh_dispatch_attention(routeable_mappings),
                    timeout=self.attention_refresh_timeout_seconds,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Dispatch attention cold refresh timed out after %.1fs; returning warmable empty queue",
                    self.attention_refresh_timeout_seconds,
                )
                scanned_jobs, items = 0, []
        normalized_status = None if status is None else status.strip().lower()
        normalized_reference = None if reference is None else reference.strip().upper()
        normalized_stage = stage.strip().lower().replace(" ", "_") if stage is not None else None
        normalized_age = age.strip().lower().replace(" ", "_") if age is not None else None
        if normalized_stage is not None:
            items = [item for item in items if item.stage == normalized_stage]
        if normalized_age is not None:
            items = [item for item in items if item.age_bucket == normalized_age]
        if technician_bluefolder_user_id is not None:
            items = [item for item in items if item.owner_bluefolder_user_id == technician_bluefolder_user_id]
        if owner_discord_user_id is not None:
            items = [item for item in items if item.assigned_owner_discord_user_id == owner_discord_user_id]
        if normalized_status is not None:
            items = [item for item in items if item.status == normalized_status]
        if normalized_reference is not None:
            items = [item for item in items if item.reference.upper() == normalized_reference]
        item_payloads = [await self._attention_item_payload(item) for item in items]
        try:
            discovery_items = await asyncio.wait_for(
                self._bluefolder_discovery_attention_payloads(
                    routeable_mappings,
                    existing_references={str(item.reference or "").upper() for item in items},
                    stage=normalized_stage,
                    age=normalized_age,
                    status=normalized_status,
                    reference=normalized_reference,
                    technician_bluefolder_user_id=technician_bluefolder_user_id,
                    owner_discord_user_id=owner_discord_user_id,
                ),
                timeout=self.discovery_scan_timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "BlueFolder discovery attention scan timed out after %.1fs",
                self.discovery_scan_timeout_seconds,
            )
            discovery_items = []
        return {
            "scannedJobs": scanned_jobs + len(discovery_items),
            "discoveryJobs": len(discovery_items),
            "filters": {
                "stage": stage,
                "age": age,
                "technicianBluefolderUserId": technician_bluefolder_user_id,
                "ownerDiscordUserId": owner_discord_user_id,
                "status": normalized_status,
                "reference": normalized_reference,
            },
            "ownerOptions": [self._dispatch_owner_option_payload(record) for record in await self._dispatch_owner_records()],
            "items": item_payloads + discovery_items,
        }

    async def get_dispatch_attention_item_payload(self, *, item_id: str) -> dict[str, object]:
        """Return a single attention item plus recent workflow history."""
        if self.workflow_state_service is None:
            raise ValueError("Dispatch attention detail requires the workflow state service.")
        item = self.workflow_state_service.get_attention_item(item_id=item_id)
        history = self.workflow_state_service.attention_history(item_id=item_id)
        return {
            "item": await self._attention_item_payload(item),
            "history": [self._workflow_event_payload(event) for event in history[:20]],
        }

    async def _bluefolder_discovery_attention_payloads(
        self,
        mappings: list[TechnicianMappingRecord],
        *,
        existing_references: set[str],
        stage: str | None,
        age: str | None,
        status: str | None,
        reference: str | None,
        technician_bluefolder_user_id: int | None,
        owner_discord_user_id: int | None,
    ) -> list[dict[str, object]]:
        """Build read-only BlueFolder assignment candidates not yet promoted to workflow attention."""
        if stage not in (None, "", "bluefolder_discovery", "discovery", "bf_discovery"):
            return []
        if age not in (None, "", "fresh"):
            return []
        if status not in (None, "", "open"):
            return []
        if owner_discord_user_id is not None:
            return []

        candidates: list[dict[str, object]] = []
        seen = set(existing_references)
        for record in mappings:
            if technician_bluefolder_user_id is not None and record.bluefolder_user_id != technician_bluefolder_user_id:
                continue
            try:
                assignments = await self._assignments_for_user(record.bluefolder_user_id, include_subjects=True)
            except Exception as exc:
                logger.warning("BlueFolder discovery assignments unavailable for %s: %s", record.bluefolder_user_id, exc)
                continue
            for assignment in assignments[:12]:
                sr_id = str(assignment.get("serviceRequestId") or "").strip()
                if not sr_id:
                    continue
                ref = f"SR-{sr_id}".upper()
                if reference is not None and ref != reference:
                    continue
                if ref in seen:
                    continue
                seen.add(ref)
                status_text = assignment.get("status") or assignment.get("serviceRequestStatus")
                address = assignment.get("address") or assignment.get("location")
                subject = assignment.get("subject") or "Service Request"
                owner_label = await self._technician_label_payload(
                    discord_user_id=record.discord_user_id,
                    bluefolder_user_id=record.bluefolder_user_id,
                )
                candidates.append(
                    {
                        "itemId": f"discovery:{ref}",
                        "srId": int(sr_id) if sr_id.isdigit() else sr_id,
                        "reference": ref,
                        "category": "discovery",
                        "status": "open",
                        "stage": "bluefolder_discovery",
                        "stageLabel": "BlueFolder Discovery",
                        "summary": f"{ref} is active in BlueFolder but has no derived OpsHub attention rule yet.",
                        "details": f"Status: {status_text or 'unknown'}",
                        "location": address,
                        "routeLabel": assignment.get("routeLabel") or assignment.get("window") or assignment.get("timeWindow"),
                        "ownerDiscordUserId": record.discord_user_id,
                        "ownerBluefolderUserId": record.bluefolder_user_id,
                        "ownerLabel": owner_label,
                        "technicianLabel": owner_label,
                        "assignedOwnerBluefolderUserId": None,
                        "assignedOwnerDiscordUserId": None,
                        "assignedOwnerLabel": "unassigned",
                        "acknowledgedAt": None,
                        "acknowledgedByUserId": None,
                        "acknowledgedByLabel": "n/a",
                        "snoozedUntil": None,
                        "snoozedByUserId": None,
                        "nextAction": "Review this BlueFolder SR and decide whether it needs scheduling, parts, quote, or closeout follow-up.",
                        "firstSeenAt": None,
                        "lastSeenAt": datetime.now().isoformat(timespec="seconds"),
                        "ageHours": 0,
                        "ageBucket": "fresh",
                        "readOnly": True,
                        "source": "bluefolder_discovery",
                        "subject": subject,
                    }
                )
                if len(candidates) >= 12:
                    return candidates
        return candidates

    async def get_dispatch_sr_customer_payload(self, *, sr_id: int) -> dict[str, object]:
        """Return structured customer and location detail for one SR."""
        async def _build() -> dict[str, object]:
            summary = await self._bluefolder_job_summary(f"SR-{sr_id}")
            address = self._format_summary_address(summary) if summary.available else None
            return {
                "srId": int(summary.service_request_id) if summary.available and str(summary.service_request_id or "").isdigit() else sr_id,
                "reference": f"SR-{summary.service_request_id or sr_id}",
                "available": summary.available,
                "integrationStatus": summary.integration_status,
                "message": summary.message,
                "subject": summary.subject,
                "customerName": summary.customer_name,
                "customerPhone": summary.customer_phone,
                "status": summary.service_request_status,
                "statusMeta": self._status_meta(summary.service_request_status),
                "address": address,
                "customerId": summary.customer_id,
                "customerLocationId": summary.customer_location_id,
                "contacts": [
                    {
                        "name": contact.name,
                        "title": contact.title,
                        "phone": contact.phone,
                        "email": contact.email,
                        "isPrimary": contact.is_primary,
                    }
                    for contact in summary.customer_contacts
                ],
            }

        return await self._cached_sr_payload("customer", sr_id, _build)

    async def get_dispatch_sr_timeline_payload(self, *, sr_id: int) -> dict[str, object]:
        """Return structured SR timeline detail for dispatch clients."""
        async def _build() -> dict[str, object]:
            if self.workflow_state_service is None:
                raise ValueError("Dispatch SR timeline requires the workflow state service.")
            timeline = await self.workflow_state_service.build_service_request_timeline(sr_id)
            return {
                "srId": timeline.sr_id,
                "reference": timeline.reference,
                "entries": [
                    {
                        "occurredAt": entry.occurred_at,
                        "source": entry.source,
                        "eventType": entry.event_type,
                        "summary": entry.summary,
                        "details": entry.details,
                        "actorLabel": entry.actor_label,
                    }
                    for entry in timeline.entries
                ],
            }

        return await self._cached_sr_payload("timeline", sr_id, _build)

    async def get_dispatch_sr_work_payload(self, *, sr_id: int) -> dict[str, object]:
        """Return dispatch work context for one SR."""
        async def _build() -> dict[str, object]:
            reference = f"SR-{sr_id}"
            summary = await self._bluefolder_job_summary(reference, include_customer_contacts=False)
            attention = await self.get_dispatch_attention_payload(reference=reference)
            parts_case = None
            photo_compliance = None
            if self.workflow_state_service is not None:
                try:
                    case = await self.workflow_state_service.get_parts_case(sr_id=sr_id)
                except ValueError:
                    case = None
                if case is not None:
                    parts_case = await self._parts_case_payload(case)
                photo_compliance = self._photo_compliance_payload(
                    self.workflow_state_service.get_cached_photo_compliance(sr_id=sr_id)
                )

            next_actions: list[str] = []
            for item in attention.get("items", []):
                action = str(item.get("nextAction") or "").strip()
                if action and action not in next_actions:
                    next_actions.append(action)
            if parts_case is not None:
                action = str(parts_case.get("nextAction") or "").strip()
                if action and action not in next_actions:
                    next_actions.append(action)

            return {
                "srId": sr_id,
                "reference": reference,
                "serviceRequestStatus": summary.service_request_status,
                "statusMeta": self._status_meta(summary.service_request_status),
                "attentionItems": attention.get("items", []),
                "partsCase": parts_case,
                "photoCompliance": photo_compliance,
                "nextActions": next_actions,
                "ownerGapCount": sum(
                    1
                    for item in attention.get("items", [])
                    if not (item.get("assignedOwnerBluefolderUserId") or item.get("assignedOwnerDiscordUserId"))
                ),
                "urgentCount": sum(1 for item in attention.get("items", []) if item.get("ageBucket") == "urgent"),
            }

        return await self._cached_sr_payload("work", sr_id, _build)

    async def get_dispatch_sr_photo_compliance_payload(self, *, sr_id: int) -> dict[str, object]:
        """Return live photo-compliance detail and persist the cached snapshot."""
        async def _build() -> dict[str, object]:
            if self.workflow_state_service is None:
                raise ValueError("Dispatch photo compliance requires the workflow state service.")
            summary = await self._bluefolder_job_summary(f"SR-{sr_id}", include_customer_contacts=False)
            record = await self.workflow_state_service.refresh_photo_compliance(
                sr_id=sr_id,
                service_request_status=summary.service_request_status,
            )
            payload = self._photo_compliance_payload(record)
            assert payload is not None
            payload["srId"] = sr_id
            return payload

        return await self._cached_sr_payload("photo-compliance", sr_id, _build)

    async def get_dispatch_sr_sms_capabilities_payload(self, *, sr_id: int) -> dict[str, object]:
        """Return SMS capability metadata for one SR."""
        async def _build() -> dict[str, object]:
            customer = await self.get_dispatch_sr_customer_payload(sr_id=sr_id)
            work = await self.get_dispatch_sr_work_payload(sr_id=sr_id)
            reference = str(customer.get("reference") or f"SR-{sr_id}")
            if self.sms_service is None:
                return {
                    "srId": sr_id,
                    "reference": reference,
                    "provider": "disabled",
                    "enabled": False,
                    "toNumber": None,
                    "fromLabel": "ARCoM Ops",
                    "reason": "SMS is not configured in Ops Hub yet.",
                    "intents": [],
                }
            return self.sms_service.capabilities_payload(
                sr_id=sr_id,
                reference=reference,
                customer=customer,
                work=work,
            )

        return await self._cached_sr_payload("sms-capabilities", sr_id, _build)

    async def get_dispatch_sr_sms_history_payload(self, *, sr_id: int) -> dict[str, object]:
        """Return recent SMS attempts for one SR."""
        if self.sms_service is None:
            return {"srId": sr_id, "items": []}
        return self.sms_service.history_payload(sr_id=sr_id)

    async def preview_dispatch_sr_sms_payload(
        self,
        *,
        sr_id: int,
        intent: str,
        custom_message: str | None = None,
    ) -> dict[str, object]:
        """Build one dispatch SR SMS preview."""
        if self.sms_service is None:
            raise ValueError("SMS is not configured in Ops Hub yet.")
        customer = await self.get_dispatch_sr_customer_payload(sr_id=sr_id)
        work = await self.get_dispatch_sr_work_payload(sr_id=sr_id)
        reference = str(customer.get("reference") or f"SR-{sr_id}")
        return self.sms_service.preview_payload(
            sr_id=sr_id,
            reference=reference,
            customer=customer,
            work=work,
            intent=intent,
            custom_message=custom_message,
        )

    async def send_dispatch_sr_sms(
        self,
        *,
        sr_id: int,
        intent: str,
        actor_user_id: int | None,
        custom_message: str | None = None,
    ) -> dict[str, object]:
        """Send one dispatch SR SMS through the configured provider seam."""
        if self.sms_service is None:
            raise ValueError("SMS is not configured in Ops Hub yet.")
        customer = await self.get_dispatch_sr_customer_payload(sr_id=sr_id)
        work = await self.get_dispatch_sr_work_payload(sr_id=sr_id)
        reference = str(customer.get("reference") or f"SR-{sr_id}")
        return await self.sms_service.send_payload(
            sr_id=sr_id,
            reference=reference,
            customer=customer,
            work=work,
            intent=intent,
            actor_user_id=actor_user_id,
            custom_message=custom_message,
        )

    async def get_dispatch_route_payload(
        self,
        *,
        technician_bluefolder_user_id: int,
        route_date: str | None = None,
        origin_address: str | None = None,
        destination_address: str | None = None,
        optimize: bool = False,
    ) -> dict[str, object]:
        """Return a structured route preview payload for one technician."""
        request = JobLookupRequest(
            reference=None,
            requested_by_user_id=0,
            technician_bluefolder_user_id=None,
            target_bluefolder_user_id=technician_bluefolder_user_id,
            route_origin_address=origin_address,
            route_destination_address=destination_address,
        )
        target_user_id = request.target_bluefolder_user_id or request.technician_bluefolder_user_id
        if target_user_id is None:
            return {
                "success": False,
                "message": "Route map lookup requires a mapped BlueFolder user. Add a technician mapping first.",
                "technicianBluefolderUserId": technician_bluefolder_user_id,
                "stops": [],
            }

        selected_date = self._parse_route_date(route_date)
        route_cache_key = self._route_payload_cache_key(
            target_user_id,
            selected_date,
            origin_address,
            destination_address,
            optimize,
        )
        cached_route = self._cache_get(route_cache_key, self.route_payload_cache_ttl_seconds)
        if isinstance(cached_route, dict):
            return self._with_cache_metadata(cached_route, "fresh")
        stale_route = self._cache_get(route_cache_key, self.route_payload_cache_ttl_seconds, allow_stale=True)
        if isinstance(stale_route, dict):
            return self._with_cache_metadata(stale_route, "stale")

        try:
            assignments = await self._assignments_for_user(target_user_id, day=selected_date)
        except Exception:
            stale_route = self._cache_get(route_cache_key, self.route_payload_cache_ttl_seconds, allow_stale=True)
            if isinstance(stale_route, dict):
                return self._with_cache_metadata(stale_route, "stale")
            raise
        technician_label = await self._technician_label(bluefolder_user_id=target_user_id)
        if not assignments:
            payload = {
                "success": True,
                "message": f"No assignments were found for {technician_label} on {selected_date.isoformat()}.",
                "technicianBluefolderUserId": target_user_id,
                "technicianLabel": technician_label,
                "routeDate": selected_date.isoformat(),
                "assignmentsConsidered": 0,
                "mappableStops": 0,
                "skippedWithoutAddress": 0,
                "originAddress": None,
                "destinationAddress": None,
                "routeUrl": None,
                "imageUrl": None,
                "stops": [],
            }
            self._cache_set(route_cache_key, payload)
            return self._with_cache_metadata(payload, "miss")

        stops: list[dict[str, object]] = []
        missing_address_count = 0
        for assignment in assignments[:10]:
            sr_id = assignment.get("serviceRequestId")
            if not isinstance(sr_id, str) or not sr_id.strip():
                continue
            summary = await self._bluefolder_job_summary(f"SR-{sr_id}")
            if not summary.available or not summary.address:
                missing_address_count += 1
                continue
            address = self._format_summary_address(summary)
            if not address:
                missing_address_count += 1
                continue
            stops.append(self._build_route_stop_payload(assignment=assignment, address=address, subject=summary.subject))

        if not stops:
            payload = {
                "success": False,
                "message": (
                    f"Assignments were found for {technician_label} on {selected_date.isoformat()}, but no mappable addresses "
                    "were available from BlueFolder."
                ),
                "technicianBluefolderUserId": target_user_id,
                "technicianLabel": technician_label,
                "routeDate": selected_date.isoformat(),
                "assignmentsConsidered": len(assignments),
                "mappableStops": 0,
                "skippedWithoutAddress": missing_address_count,
                "originAddress": self._clean_route_endpoint(request.route_origin_address),
                "destinationAddress": self._clean_route_endpoint(request.route_destination_address),
                "routeUrl": None,
                "imageUrl": None,
                "stops": [],
            }
            self._cache_set(route_cache_key, payload)
            return self._with_cache_metadata(payload, "miss")

        route_origin_address = self._clean_route_endpoint(request.route_origin_address)
        route_destination_address = self._clean_route_endpoint(request.route_destination_address)
        planned_route = await self.adapter.preview_route_plan(
            stops,
            origin_address=route_origin_address,
            destination_address=route_destination_address,
            optimize=optimize,
        )
        planned_stops = planned_route.get("stops") if isinstance(planned_route, dict) else None
        route_stops = planned_stops if isinstance(planned_stops, list) and planned_stops else stops

        try:
            route_url, image_url = await self.adapter.build_route_map_urls(
                route_stops,
                origin_address=route_origin_address,
                destination_address=route_destination_address,
            )
        except TypeError:
            route_url, image_url = await self.adapter.build_route_map_urls(route_stops)
        route_path = planned_route.get("path") if isinstance(planned_route, dict) else []
        if not route_path:
            try:
                route_stops, route_path = await self.adapter.enrich_route_geometry(
                    route_stops,
                    origin_address=route_origin_address,
                    destination_address=route_destination_address,
                )
            except AttributeError:
                route_path = []

        payload = {
            "success": True,
            "message": f"Route map ready for {technician_label}.",
            "technicianBluefolderUserId": target_user_id,
            "technicianLabel": technician_label,
            "routeDate": selected_date.isoformat(),
            "assignmentsConsidered": len(assignments),
            "mappableStops": len(stops),
            "skippedWithoutAddress": missing_address_count,
            "originAddress": route_origin_address,
            "destinationAddress": route_destination_address,
            "optimized": optimize,
            "routeUrl": route_url,
            "imageUrl": image_url,
            "stops": route_stops,
            "metrics": planned_route.get("metrics") if isinstance(planned_route, dict) else None,
            "path": route_path,
        }
        self._cache_set(route_cache_key, payload)
        return self._with_cache_metadata(payload, "miss")

    async def get_dispatch_route_simulation_payload(
        self,
        *,
        technician_bluefolder_user_id: int | None,
        existing_stops: list[dict[str, object]],
        added_stops: list[dict[str, object]],
        removed_ids: list[str],
        manual_order: list[str],
        route_date: str | None = None,
        origin_address: str | None = None,
        destination_address: str | None = None,
        optimize: bool = False,
    ) -> dict[str, object]:
        """Return a simulated route payload using manual order, removals, and ad-hoc additions."""
        normalized_existing = [
            self._normalize_route_stop_input(stop, index=index)
            for index, stop in enumerate(existing_stops)
        ]
        normalized_added = [
            self._normalize_route_stop_input(stop, index=index, adhoc=True)
            for index, stop in enumerate(added_stops)
        ]
        kept_existing = [stop for stop in normalized_existing if stop["id"] not in {str(item) for item in removed_ids}]
        technician_label = await self._technician_label(bluefolder_user_id=technician_bluefolder_user_id)
        selected_date = self._parse_route_date(route_date)
        route_origin_address = self._clean_route_endpoint(origin_address)
        route_destination_address = self._clean_route_endpoint(destination_address)

        planned_route = await self.adapter.simulate_route_plan(
            existing_assignments=kept_existing,
            added_stops=normalized_added,
            removed_ids=[str(item) for item in removed_ids],
            manual_order=[str(item) for item in manual_order],
            origin_address=route_origin_address,
            destination_address=route_destination_address,
            optimize=optimize,
        )

        route_stops = planned_route.get("stops") if isinstance(planned_route, dict) else None
        if not isinstance(route_stops, list):
            route_stops = normalized_added + kept_existing
            if manual_order:
                order_lookup = {value: index for index, value in enumerate(str(item) for item in manual_order)}
                route_stops = sorted(route_stops, key=lambda stop: order_lookup.get(str(stop.get("id")), len(order_lookup)))

        try:
            route_url, image_url = await self.adapter.build_route_map_urls(
                route_stops,
                origin_address=route_origin_address,
                destination_address=route_destination_address,
            )
        except TypeError:
            route_url, image_url = await self.adapter.build_route_map_urls(route_stops)
        route_path = planned_route.get("path") if isinstance(planned_route, dict) else []
        if not route_path:
            try:
                route_stops, route_path = await self.adapter.enrich_route_geometry(
                    route_stops,
                    origin_address=route_origin_address,
                    destination_address=route_destination_address,
                )
            except AttributeError:
                route_path = []

        return {
            "success": True,
            "message": f"Route draft updated for {technician_label}.",
            "technicianBluefolderUserId": technician_bluefolder_user_id,
            "technicianLabel": technician_label,
            "routeDate": selected_date.isoformat(),
            "assignmentsConsidered": len(existing_stops),
            "mappableStops": len(route_stops),
            "skippedWithoutAddress": 0,
            "originAddress": route_origin_address,
            "destinationAddress": route_destination_address,
            "optimized": optimize,
            "routeUrl": route_url,
            "imageUrl": image_url,
            "stops": route_stops,
            "metrics": planned_route.get("metrics") if isinstance(planned_route, dict) else None,
            "path": route_path,
        }

    async def get_dispatch_heatmap_payload(
        self,
        *,
        technician_bluefolder_user_id: int | None = None,
    ) -> dict[str, object]:
        """Return a structured assignment heatmap payload."""
        mappings = await self._dispatch_operator_records()
        if not mappings:
            return {
                "success": False,
                "message": "Dispatch heatmap requires at least one technician mapping.",
                "scannedJobs": 0,
                "uniqueMappedLocations": 0,
                "imageUrl": None,
                "hotspots": [],
            }

        if technician_bluefolder_user_id is not None:
            mappings = [record for record in mappings if record.bluefolder_user_id == technician_bluefolder_user_id]
            if not mappings:
                return {
                    "success": False,
                    "message": (
                        "Dispatch heatmap could not find a technician mapping for "
                        f"{await self._technician_label(bluefolder_user_id=technician_bluefolder_user_id)}."
                    ),
                    "scannedJobs": 0,
                    "uniqueMappedLocations": 0,
                    "imageUrl": None,
                    "hotspots": [],
                }

        heatmap_cache_key = self._heatmap_payload_cache_key(
            technician_bluefolder_user_id,
            [record.bluefolder_user_id for record in mappings],
        )
        cached_heatmap = self._cache_get(heatmap_cache_key, self.heatmap_payload_cache_ttl_seconds)
        if isinstance(cached_heatmap, dict):
            return self._with_cache_metadata(cached_heatmap, "fresh")
        stale_heatmap = self._cache_get(heatmap_cache_key, self.heatmap_payload_cache_ttl_seconds, allow_stale=True)
        if isinstance(stale_heatmap, dict):
            return self._with_cache_metadata(stale_heatmap, "stale")

        hotspot_counts: dict[str, int] = {}
        address_labels: dict[str, str] = {}
        scanned_jobs = 0
        for record in mappings:
            try:
                assignments = await self._assignments_for_user(record.bluefolder_user_id)
            except Exception:
                stale_heatmap = self._cache_get(
                    heatmap_cache_key,
                    self.heatmap_payload_cache_ttl_seconds,
                    allow_stale=True,
                )
                if isinstance(stale_heatmap, dict):
                    return self._with_cache_metadata(stale_heatmap, "stale")
                raise
            for assignment in assignments[:10]:
                sr_id = assignment.get("serviceRequestId")
                if not isinstance(sr_id, str) or not sr_id.strip():
                    continue
                scanned_jobs += 1
                summary = await self._bluefolder_job_summary(f"SR-{sr_id}")
                address = self._format_summary_address(summary)
                if not summary.available or not address:
                    continue
                hotspot_counts[address] = hotspot_counts.get(address, 0) + 1
                address_labels.setdefault(address, summary.city or summary.address or address)

        if not hotspot_counts:
            payload = {
                "success": False,
                "message": "No mappable assignment addresses were available for the current heatmap.",
                "scannedJobs": scanned_jobs,
                "uniqueMappedLocations": 0,
                "imageUrl": None,
                "hotspots": [],
            }
            self._cache_set(heatmap_cache_key, payload)
            return self._with_cache_metadata(payload, "miss")

        hotspots = [
            {
                "address": address,
                "count": count,
                "label": address_labels.get(address, address),
            }
            for address, count in sorted(hotspot_counts.items(), key=lambda item: (-item[1], item[0]))
        ]
        image_url = await self.adapter.build_heat_map_url(
            [{"address": item["address"], "count": item["count"]} for item in hotspots]
        )
        payload = {
            "success": True,
            "message": "Dispatch heatmap ready.",
            "technicianBluefolderUserId": technician_bluefolder_user_id,
            "technicianLabel": (
                await self._technician_label(bluefolder_user_id=technician_bluefolder_user_id)
                if technician_bluefolder_user_id is not None
                else None
            ),
            "scannedJobs": scanned_jobs,
            "uniqueMappedLocations": len(hotspots),
            "imageUrl": image_url,
            "hotspots": hotspots,
        }
        self._cache_set(heatmap_cache_key, payload)
        return self._with_cache_metadata(payload, "miss")

    async def acknowledge_dispatch_attention_item(self, *, item_id: str, actor_user_id: int) -> dict[str, object]:
        """Acknowledge one attention item by item id."""
        item = self._get_attention_item_for_action(item_id=item_id)
        result = await self.acknowledge_dispatch_attention(sr_id=item.sr_id, stage=item.stage, actor_user_id=actor_user_id)
        updated = self._get_attention_item_for_action(item_id=item.item_id)
        return {"success": True, "message": result.message, "item": await self._attention_item_payload(updated)}

    async def snooze_dispatch_attention_item(
        self,
        *,
        item_id: str,
        hours: int,
        actor_user_id: int,
    ) -> dict[str, object]:
        """Snooze one attention item by item id."""
        item = self._get_attention_item_for_action(item_id=item_id)
        result = await self.snooze_dispatch_attention(
            sr_id=item.sr_id,
            stage=item.stage,
            hours=hours,
            actor_user_id=actor_user_id,
        )
        updated = self._get_attention_item_for_action(item_id=item.item_id)
        return {"success": True, "message": result.message, "item": await self._attention_item_payload(updated)}

    async def unsnooze_dispatch_attention_item(self, *, item_id: str, actor_user_id: int) -> dict[str, object]:
        """Unsnooze one attention item by item id."""
        item = self._get_attention_item_for_action(item_id=item_id)
        result = await self.unsnooze_dispatch_attention(sr_id=item.sr_id, stage=item.stage, actor_user_id=actor_user_id)
        updated = self._get_attention_item_for_action(item_id=item.item_id)
        return {"success": True, "message": result.message, "item": await self._attention_item_payload(updated)}

    async def reopen_dispatch_attention_item(self, *, item_id: str, actor_user_id: int) -> dict[str, object]:
        """Reopen one attention item by item id."""
        item = self._get_attention_item_for_action(item_id=item_id)
        result = await self.reopen_dispatch_attention(sr_id=item.sr_id, stage=item.stage, actor_user_id=actor_user_id)
        updated = self._get_attention_item_for_action(item_id=item.item_id)
        return {"success": True, "message": result.message, "item": await self._attention_item_payload(updated)}

    async def set_dispatch_triage_disposition_item(
        self,
        *,
        item_id: str,
        disposition: str,
        actor_user_id: int,
        details: str | None = None,
    ) -> dict[str, object]:
        """Record triage disposition for one item id."""
        item = self._get_attention_item_for_action(item_id=item_id)
        result = await self.set_dispatch_triage_disposition(
            sr_id=item.sr_id,
            disposition=disposition,
            actor_user_id=actor_user_id,
            details=details,
        )
        return {"success": True, "message": result.message, "reference": item.reference, "srId": item.sr_id}

    async def assign_dispatch_attention_item(
        self,
        *,
        item_id: str,
        assigned_owner_bluefolder_user_id: int | None = None,
        assigned_owner_discord_user_id: int | None = None,
        actor_user_id: int,
    ) -> dict[str, object]:
        """Assign one attention item by item id."""
        item = self._get_attention_item_for_action(item_id=item_id)
        result = await self.assign_dispatch_attention_owner(
            sr_id=item.sr_id,
            stage=item.stage,
            assigned_owner_bluefolder_user_id=assigned_owner_bluefolder_user_id,
            assigned_owner_discord_user_id=assigned_owner_discord_user_id,
            actor_user_id=actor_user_id,
        )
        updated = self._get_attention_item_for_action(item_id=item.item_id)
        return {"success": True, "message": result.message, "item": await self._attention_item_payload(updated)}

    async def clear_dispatch_attention_item_owner(self, *, item_id: str, actor_user_id: int) -> dict[str, object]:
        """Clear owner on one attention item by item id."""
        item = self._get_attention_item_for_action(item_id=item_id)
        result = await self.clear_dispatch_attention_owner(sr_id=item.sr_id, stage=item.stage, actor_user_id=actor_user_id)
        updated = self._get_attention_item_for_action(item_id=item.item_id)
        return {"success": True, "message": result.message, "item": await self._attention_item_payload(updated)}

    async def apply_bulk_dispatch_attention_action(
        self,
        *,
        item_ids: list[str],
        action: str,
        actor_user_id: int,
        action_body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Apply one action across multiple attention items."""
        normalized_ids: list[str] = []
        for item_id in item_ids:
            normalized = item_id.strip()
            if normalized and normalized not in normalized_ids:
                normalized_ids.append(normalized)
        if not normalized_ids:
            raise ValueError("itemIds must contain at least one attention item id.")

        payload_body = action_body or {}
        results: list[dict[str, object]] = []
        updated_items: list[dict[str, object]] = []
        success_count = 0

        for item_id in normalized_ids:
            try:
                if action == "ack":
                    payload = await self.acknowledge_dispatch_attention_item(item_id=item_id, actor_user_id=actor_user_id)
                elif action == "snooze":
                    payload = await self.snooze_dispatch_attention_item(
                        item_id=item_id,
                        hours=int(payload_body.get("hours") or 1),
                        actor_user_id=actor_user_id,
                    )
                elif action == "unsnooze":
                    payload = await self.unsnooze_dispatch_attention_item(item_id=item_id, actor_user_id=actor_user_id)
                elif action == "reopen":
                    payload = await self.reopen_dispatch_attention_item(item_id=item_id, actor_user_id=actor_user_id)
                elif action == "assign":
                    assigned_owner_bluefolder_user_id = int(
                        payload_body.get("assignedOwnerBluefolderUserId")
                        or self._bluefolder_user_id_for_discord_user_id(int(payload_body.get("assignedOwnerDiscordUserId") or 0))
                        or 0
                    )
                    payload = await self.assign_dispatch_attention_item(
                        item_id=item_id,
                        assigned_owner_bluefolder_user_id=assigned_owner_bluefolder_user_id or None,
                        assigned_owner_discord_user_id=int(payload_body.get("assignedOwnerDiscordUserId") or 0) or None,
                        actor_user_id=actor_user_id,
                    )
                elif action == "clear_owner":
                    payload = await self.clear_dispatch_attention_item_owner(item_id=item_id, actor_user_id=actor_user_id)
                else:
                    raise ValueError(f"Unsupported bulk attention action: {action}")
                success_count += 1
                if isinstance(payload.get("item"), dict):
                    updated_items.append(payload["item"])
                results.append({"itemId": item_id, "success": True, "message": str(payload.get("message") or "")})
            except ValueError as exc:
                results.append({"itemId": item_id, "success": False, "message": str(exc)})

        return {
            "success": success_count == len(normalized_ids),
            "message": f"Applied {action} to {success_count} of {len(normalized_ids)} attention item(s).",
            "action": action,
            "requestedCount": len(normalized_ids),
            "successCount": success_count,
            "failureCount": len(normalized_ids) - success_count,
            "results": results,
            "items": updated_items,
        }

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
            summary = await self._bluefolder_job_summary(f"SR-{sr_id}")
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
                summary = await self._bluefolder_job_summary(f"SR-{sr_id}")
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

    async def _dispatch_operator_records(self) -> list[TechnicianMappingRecord]:
        """Return BlueFolder-first operator records for dispatch surfaces."""
        if self.technician_directory_service is None:
            return []
        operator_records = getattr(self.technician_directory_service, "operator_records", None)
        if callable(operator_records):
            return await operator_records(bluefolder_service=self.bluefolder_service)
        return self.technician_directory_service.mapping_records()

    async def _dispatch_owner_records(self) -> list[TechnicianMappingRecord]:
        """Return BlueFolder-backed follow-up owner choices for dispatch surfaces."""
        if self.technician_directory_service is None:
            return []
        owner_records = getattr(self.technician_directory_service, "dispatch_owner_records", None)
        if callable(owner_records):
            return await owner_records(bluefolder_service=self.bluefolder_service)
        return []

    @staticmethod
    def _is_dispatch_board_candidate(record: TechnicianMappingRecord) -> bool:
        """Return whether a BlueFolder operator should appear as a routeable technician."""
        from ops_hub.services.operator_directory import TechnicianDirectoryService

        return TechnicianDirectoryService.is_routeable_technician_record(record)

    def _get_attention_item_for_action(self, *, item_id: str):
        """Resolve one attention item before mutating it."""
        if self.workflow_state_service is None:
            raise ValueError("Dispatch attention actions require the workflow state service.")
        return self.workflow_state_service.get_attention_item(item_id=item_id)

    async def _technician_label_payload(
        self,
        *,
        discord_user_id: int | None = None,
        bluefolder_user_id: int | None = None,
    ) -> str | None:
        if discord_user_id is None and bluefolder_user_id is None:
            return None
        return await self._technician_label(
            discord_user_id=discord_user_id,
            bluefolder_user_id=bluefolder_user_id,
        )

    def _dispatch_owner_option_payload(self, record: TechnicianMappingRecord) -> dict[str, object]:
        return {
            "bluefolderUserId": record.bluefolder_user_id,
            "discordUserId": record.discord_user_id,
            "label": record.bluefolder_name or record.display_name or record.global_name or record.username or f"Tech {record.bluefolder_user_id}",
            "role": record.bluefolder_role,
            "roles": list(record.bluefolder_roles),
        }

    def _workflow_event_payload(self, event) -> dict[str, object]:
        """Serialize a workflow event for API responses."""
        return {
            "eventId": event.event_id,
            "eventType": event.event_type,
            "source": event.source,
            "occurredAt": event.occurred_at,
            "summary": event.summary,
            "srId": event.sr_id,
            "reference": event.reference,
            "actorUserId": event.actor_user_id,
            "actorLabel": event.actor_label,
            "details": event.details,
            "metadata": event.metadata,
        }

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
        if record.discord_user_id is not None:
            return await self._technician_label(discord_user_id=record.discord_user_id)
        return await self._technician_label(bluefolder_user_id=record.bluefolder_user_id)

    async def _board_technician_label_for_record(
        self,
        record: TechnicianMappingRecord,
    ) -> str:
        """Render a BlueFolder-first technician label for the dispatch board."""
        if record.bluefolder_user_id is not None:
            return await self._bluefolder_label(record.bluefolder_user_id, markdown=False)
        return await self._technician_label_for_record(record)

    async def _format_attention_action_result(self, action: str, item) -> str:
        """Render a concise response for one attention mutation."""
        lines = [
            f"**{action} Attention Item**",
            f"Reference: `{item.reference}`",
            f"Stage: `{item.stage_label}`",
            f"Status: `{item.status}`",
        ]
        if item.assigned_owner_bluefolder_user_id is not None:
            owner_label = await self._technician_label(
                discord_user_id=item.assigned_owner_discord_user_id,
                bluefolder_user_id=None if item.assigned_owner_discord_user_id is not None else item.assigned_owner_bluefolder_user_id,
            )
            lines.append(f"Follow-up owner: {owner_label}")
        if item.snoozed_until:
            lines.append(f"Snoozed until: `{item.snoozed_until}`")
        if item.next_action:
            lines.append(f"Next action: {item.next_action}")
        return "\n".join(lines)

    async def _attention_item_payload(self, item) -> dict[str, object]:
        """Serialize one attention item for API responses."""
        return {
            "itemId": item.item_id,
            "srId": item.sr_id,
            "reference": item.reference,
            "category": item.category,
            "status": item.status,
            "stage": item.stage,
            "stageLabel": item.stage_label,
            "summary": item.summary,
            "details": item.details,
            "location": item.location,
            "routeLabel": item.route_label,
            "ownerDiscordUserId": item.owner_discord_user_id,
            "ownerBluefolderUserId": item.owner_bluefolder_user_id,
            "ownerLabel": await self._technician_label_payload(
                discord_user_id=item.owner_discord_user_id,
                bluefolder_user_id=item.owner_bluefolder_user_id,
            ),
            "technicianLabel": await self._technician_label_payload(
                discord_user_id=item.owner_discord_user_id,
                bluefolder_user_id=item.owner_bluefolder_user_id,
            ),
            "assignedOwnerBluefolderUserId": item.assigned_owner_bluefolder_user_id,
            "assignedOwnerDiscordUserId": item.assigned_owner_discord_user_id,
            "assignedOwnerLabel": await self._technician_label_payload(
                discord_user_id=item.assigned_owner_discord_user_id,
                bluefolder_user_id=item.assigned_owner_bluefolder_user_id,
            ),
            "acknowledgedAt": item.acknowledged_at,
            "acknowledgedByUserId": item.acknowledged_by_user_id,
            "acknowledgedByLabel": await self._technician_label_payload(
                discord_user_id=item.acknowledged_by_user_id,
            ),
            "snoozedUntil": item.snoozed_until,
            "snoozedByUserId": item.snoozed_by_user_id,
            "nextAction": item.next_action,
            "firstSeenAt": item.first_seen_at,
            "lastSeenAt": item.last_seen_at,
            "ageHours": item.age_hours,
            "ageBucket": item.age_bucket,
            "photoCompliance": self._inline_photo_compliance_payload(
                enabled=item.photo_enabled,
                mailbox_status=item.photo_mailbox_status,
                total_photos=item.photo_total,
                found_tags=item.photo_found_tags,
                missing_tags=item.photo_missing_tags,
                checked_at=item.photo_checked_at,
                should_notify=item.photo_should_notify,
                reason=item.photo_reason,
            ),
        }

    async def _parts_case_payload(self, case) -> dict[str, object]:
        """Serialize one parts case for API responses."""
        return {
            "caseId": case.case_id,
            "reference": case.reference,
            "srId": case.sr_id,
            "stage": case.stage,
            "stageLabel": case.stage_label,
            "status": case.status,
            "openRequestIds": case.open_request_ids,
            "assignedPartsUserId": case.assigned_parts_user_id,
            "assignedPartsLabel": await self._technician_label_payload(discord_user_id=case.assigned_parts_user_id),
            "requestedByUserId": case.requested_by_user_id,
            "requestedByLabel": await self._technician_label_payload(discord_user_id=case.requested_by_user_id),
            "technicianBluefolderUserId": case.technician_bluefolder_user_id,
            "technicianLabel": await self._technician_label_payload(bluefolder_user_id=case.technician_bluefolder_user_id),
            "serviceRequestStatus": case.service_request_status,
            "serviceRequestStatusMeta": self._status_meta(case.service_request_status),
            "latestStatusText": case.latest_status_text,
            "latestIssueText": case.latest_issue_text,
            "blocker": case.blocker,
            "nextAction": case.next_action,
            "updatedAt": case.updated_at,
            "ageHours": case.age_hours,
            "ageBucket": case.age_bucket,
            "photoCompliance": self._inline_photo_compliance_payload(
                enabled=case.photo_enabled,
                mailbox_status=case.photo_mailbox_status,
                total_photos=case.photo_total,
                found_tags=case.photo_found_tags,
                missing_tags=case.photo_missing_tags,
                checked_at=case.photo_checked_at,
                should_notify=case.photo_should_notify,
                reason=case.photo_reason,
            ),
        }

    @staticmethod
    def _photo_compliance_payload(record) -> dict[str, object] | None:
        """Serialize one cached photo-compliance record."""
        if record is None:
            return None
        return {
            "enabled": record.enabled,
            "mailboxStatus": record.mailbox_status,
            "totalPhotos": record.total_photos,
            "foundTags": list(record.found_tags),
            "missingTags": list(record.missing_tags),
            "matchedRequiredStatus": record.matched_required_status,
            "shouldNotify": record.should_notify,
            "serviceRequestStatus": record.service_request_status,
            "reason": record.reason,
            "message": record.message,
            "checkedAt": record.checked_at,
        }

    @staticmethod
    def _inline_photo_compliance_payload(
        *,
        enabled: bool,
        mailbox_status: str | None,
        total_photos: int,
        found_tags: list[str],
        missing_tags: list[str],
        checked_at: str | None,
        should_notify: bool,
        reason: str | None,
    ) -> dict[str, object] | None:
        """Serialize lightweight cached photo-compliance fields on workflow payloads."""
        if not enabled and not mailbox_status and not checked_at and not missing_tags and total_photos <= 0:
            return None
        return {
            "enabled": enabled,
            "mailboxStatus": mailbox_status,
            "totalPhotos": total_photos,
            "foundTags": list(found_tags),
            "missingTags": list(missing_tags),
            "checkedAt": checked_at,
            "shouldNotify": should_notify,
            "reason": reason,
        }

    async def _technician_label(
        self,
        *,
        discord_user_id: int | None = None,
        bluefolder_user_id: int | None = None,
    ) -> str:
        """Render the best available technician label for dispatch messages."""
        if bluefolder_user_id is not None:
            return await self._bluefolder_label(bluefolder_user_id, markdown=True)
        if discord_user_id is not None and self.technician_directory_service is not None:
            display_label_fn = getattr(self.technician_directory_service, "display_label", None)
            if callable(display_label_fn):
                display_label = display_label_fn(discord_user_id)
                if display_label:
                    return display_label
            discord_mention = getattr(self.technician_directory_service, "discord_mention", None)
            if callable(discord_mention):
                return discord_mention(discord_user_id)
            return f"<@{discord_user_id}>"
        if discord_user_id is not None:
            return f"<@{discord_user_id}>"
        return "Unknown technician"

    async def _bluefolder_label(self, bluefolder_user_id: int, *, markdown: bool) -> str:
        """Render a BlueFolder-first label, falling back to a BlueFolder-specific identifier."""
        get_user_name = getattr(self.bluefolder_service, "get_user_name", None)
        if callable(get_user_name):
            user_name = await get_user_name(bluefolder_user_id)
            if user_name:
                return user_name
        if self.technician_directory_service is not None:
            technician_display_label = getattr(self.technician_directory_service, "technician_display_label", None)
            if callable(technician_display_label):
                label = technician_display_label(bluefolder_user_id=bluefolder_user_id)
                if label:
                    return label
        if markdown:
            return f"BlueFolder user `{bluefolder_user_id}`"
        return f"BlueFolder {bluefolder_user_id}"

    def _bluefolder_user_id_for_discord_user_id(self, discord_user_id: int | None) -> int | None:
        """Resolve a mapped BlueFolder user id from a Discord user id when available."""
        if discord_user_id is None or self.technician_directory_service is None:
            return None
        mappings = getattr(self.technician_directory_service, "mappings", None)
        if callable(mappings):
            return mappings().get(discord_user_id)
        return None

    async def _assignments_for_user(
        self,
        bluefolder_user_id: int,
        *,
        day: date | None = None,
        include_subjects: bool = True,
    ) -> list[dict[str, str | bool | None]]:
        """Load assignments for one day, preferring direct BlueFolder reads with a wrapper fallback."""
        target_day = day or date.today()
        cache_key = self._assignment_cache_key(bluefolder_user_id, target_day, include_subjects)
        cached = self._cache_get(cache_key, self.assignment_cache_ttl_seconds)
        if isinstance(cached, list):
            return cached
        stale_assignments = self._cache_get(cache_key, self.assignment_cache_ttl_seconds, allow_stale=True)
        if isinstance(stale_assignments, list):
            logger.info(
                "Serving stale BlueFolder assignments for mapped user %s on %s",
                bluefolder_user_id,
                target_day.isoformat(),
            )
            return stale_assignments

        async def _fetch() -> list[dict[str, str | bool | None]]:
            try:
                assignments = await self.bluefolder_service.get_assignments_for_user_on_date(
                    bluefolder_user_id,
                    target_day,
                    include_subjects=include_subjects,
                )
            except Exception as exc:
                logger.warning(
                    "BlueFolder assignments unavailable for mapped user %s on %s: %s",
                    bluefolder_user_id,
                    target_day.isoformat(),
                    exc,
                )
                assignments = []
            if assignments:
                return assignments
            return await self.adapter.get_assignments_for_user(bluefolder_user_id)

        try:
            assignments = await self._singleflight(cache_key, _fetch)
        except Exception:
            stale_assignments = self._cache_get(cache_key, self.assignment_cache_ttl_seconds, allow_stale=True)
            if isinstance(stale_assignments, list):
                logger.warning(
                    "Serving stale BlueFolder assignments for mapped user %s on %s after refresh failure",
                    bluefolder_user_id,
                    target_day.isoformat(),
                )
                return stale_assignments
            raise
        self._cache_set(cache_key, assignments)
        return deepcopy(assignments)

    async def _bluefolder_job_summary(self, reference: str, *, include_customer_contacts: bool = True) -> BlueFolderJobSummary:
        """Return a cached BlueFolder SR summary and collapse concurrent identical lookups."""
        cache_key = self._job_summary_cache_key(reference, include_customer_contacts)
        cached = self._cache_get(cache_key, self.job_summary_cache_ttl_seconds)
        if cached is not None:
            return cached
        stale_summary = self._cache_get(cache_key, self.job_summary_cache_ttl_seconds, allow_stale=True)
        if stale_summary is not None:
            logger.info("Serving stale BlueFolder SR summary for %s", reference)
            return stale_summary

        async def _fetch() -> BlueFolderJobSummary:
            try:
                return await self.bluefolder_service.get_job_summary(
                    reference,
                    include_customer_contacts=include_customer_contacts,
                )
            except TypeError:
                return await self.bluefolder_service.get_job_summary(reference)

        try:
            summary = await self._singleflight(cache_key, _fetch)
        except Exception:
            stale_summary = self._cache_get(cache_key, self.job_summary_cache_ttl_seconds, allow_stale=True)
            if stale_summary is not None:
                logger.warning("Serving stale BlueFolder SR summary for %s after refresh failure", reference)
                return stale_summary
            raise
        self._cache_set(cache_key, summary)
        return deepcopy(summary)

    async def _cached_sr_payload(self, section: str, sr_id: int, factory) -> dict[str, object]:
        """Return a cached SR section payload, falling back to stale data when live reads fail."""
        cache_key = self._sr_payload_cache_key(section, sr_id)
        cached = self._cache_get(cache_key, self.sr_payload_cache_ttl_seconds)
        if isinstance(cached, dict):
            return self._with_cache_metadata(cached, "fresh")
        try:
            payload = await factory()
        except Exception:
            stale = self._cache_get(cache_key, self.sr_payload_cache_ttl_seconds, allow_stale=True)
            if isinstance(stale, dict):
                logger.warning(
                    "Serving stale dispatch SR %s payload for SR-%s after refresh failure",
                    section,
                    sr_id,
                )
                return self._with_cache_metadata(stale, "stale")
            raise
        self._cache_set(cache_key, payload)
        return self._with_cache_metadata(payload, "miss")

    def _cache_get(self, key: str, ttl_seconds: float, *, allow_stale: bool = False) -> object | None:
        now = time.monotonic()
        with self._cache_lock:
            entry = self._cache_entries.get(key)
            if entry is not None:
                stored_at, value = entry
                max_age = self.persistent_cache_stale_ttl_seconds if allow_stale else ttl_seconds
                age = now - stored_at
                if age <= max_age:
                    return deepcopy(value)
                if age > self.persistent_cache_stale_ttl_seconds:
                    self._cache_entries.pop(key, None)

        persistent_value = self._persistent_cache_get(key, ttl_seconds, allow_stale=allow_stale)
        if persistent_value is None:
            return None
        with self._cache_lock:
            self._cache_entries[key] = (time.monotonic(), deepcopy(persistent_value))
        return deepcopy(persistent_value)

    def _cache_set(self, key: str, value: object) -> None:
        with self._cache_lock:
            self._cache_entries[key] = (time.monotonic(), deepcopy(value))
        self._persistent_cache_set(key, value)

    def _persistent_cache_get(self, key: str, ttl_seconds: float, *, allow_stale: bool = False) -> object | None:
        if self.persistent_cache_path is None:
            return None
        try:
            self._ensure_persistent_cache()
            with sqlite3.connect(self.persistent_cache_path) as connection:
                row = connection.execute(
                    "SELECT created_at, payload FROM dispatch_cache WHERE cache_key = ?",
                    (key,),
                ).fetchone()
            if row is None:
                return None
            created_at, payload = row
            max_age = self.persistent_cache_stale_ttl_seconds if allow_stale else ttl_seconds
            if time.time() - float(created_at) > max_age:
                return None
            return pickle.loads(payload)
        except Exception as exc:
            logger.warning("Persistent dispatch cache read failed for %s: %s", key, exc)
            return None

    def _persistent_cache_set(self, key: str, value: object) -> None:
        if self.persistent_cache_path is None:
            return
        try:
            self._ensure_persistent_cache()
            payload = pickle.dumps(deepcopy(value), protocol=pickle.HIGHEST_PROTOCOL)
            with sqlite3.connect(self.persistent_cache_path) as connection:
                connection.execute(
                    """
                    INSERT INTO dispatch_cache(cache_key, created_at, payload)
                    VALUES (?, ?, ?)
                    ON CONFLICT(cache_key) DO UPDATE SET
                        created_at = excluded.created_at,
                        payload = excluded.payload
                    """,
                    (key, time.time(), payload),
                )
                connection.commit()
        except Exception as exc:
            logger.warning("Persistent dispatch cache write failed for %s: %s", key, exc)

    def _persistent_cache_delete(self, key: str) -> None:
        if self.persistent_cache_path is None:
            return
        try:
            self._ensure_persistent_cache()
            with sqlite3.connect(self.persistent_cache_path) as connection:
                connection.execute("DELETE FROM dispatch_cache WHERE cache_key = ?", (key,))
                connection.commit()
        except Exception as exc:
            logger.warning("Persistent dispatch cache delete failed for %s: %s", key, exc)

    def _ensure_persistent_cache(self) -> None:
        if self.persistent_cache_path is None:
            return
        with self._cache_lock:
            if self._persistent_cache_ready:
                return
            self.persistent_cache_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.persistent_cache_path) as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS dispatch_cache (
                        cache_key TEXT PRIMARY KEY,
                        created_at REAL NOT NULL,
                        payload BLOB NOT NULL
                    )
                    """
                )
                connection.commit()
            self._persistent_cache_ready = True

    async def _singleflight(self, key: str, factory):
        current_loop = asyncio.get_running_loop()
        with self._cache_lock:
            entry = self._inflight_tasks.get(key)
            task = entry[1] if entry is not None else None
            task_loop = entry[0] if entry is not None else None
            if task is None or task.done() or task_loop is not current_loop:
                task = asyncio.create_task(factory())
                self._inflight_tasks[key] = (current_loop, task)
        try:
            return await task
        finally:
            if task.done():
                with self._cache_lock:
                    if self._inflight_tasks.get(key) == (current_loop, task):
                        self._inflight_tasks.pop(key, None)

    @staticmethod
    def _assignment_cache_key(bluefolder_user_id: int, target_day: date, include_subjects: bool) -> str:
        return f"dispatch:assignments:{bluefolder_user_id}:{target_day.isoformat()}:{int(include_subjects)}"

    @staticmethod
    def _job_summary_cache_key(reference: str, include_customer_contacts: bool) -> str:
        normalized = str(reference or "").strip().upper()
        return f"dispatch:job-summary:{normalized}:{int(include_customer_contacts)}"

    @staticmethod
    def _sr_payload_cache_key(section: str, sr_id: int) -> str:
        normalized_section = str(section or "").strip().lower()
        return f"dispatch:sr-payload:{normalized_section}:{int(sr_id)}"

    @staticmethod
    def _route_payload_cache_key(
        bluefolder_user_id: int,
        target_day: date,
        origin_address: str | None,
        destination_address: str | None,
        optimize: bool,
    ) -> str:
        origin = str(origin_address or "").strip().lower()
        destination = str(destination_address or "").strip().lower()
        return f"dispatch:route:{bluefolder_user_id}:{target_day.isoformat()}:{origin}:{destination}:{int(optimize)}"

    @staticmethod
    def _heatmap_payload_cache_key(bluefolder_user_id: int | None, mapped_user_ids: list[int]) -> str:
        scope = str(bluefolder_user_id) if bluefolder_user_id is not None else "all"
        mapped = ",".join(str(user_id) for user_id in sorted(mapped_user_ids))
        return f"dispatch:heatmap:{scope}:{mapped}:{date.today().isoformat()}"

    @staticmethod
    def _with_cache_metadata(payload: dict[str, object], status: str) -> dict[str, object]:
        next_payload = dict(payload)
        next_payload.setdefault("cacheStatus", status)
        next_payload.setdefault("cached", status in {"fresh", "stale"})
        if status == "stale":
            next_payload.setdefault("message", "Showing cached dispatch data while OpsHub refreshes BlueFolder.")
        return next_payload

    @staticmethod
    def _parse_route_date(raw_value: str | None) -> date:
        text = str(raw_value or "").strip()
        if not text:
            return date.today()
        try:
            return date.fromisoformat(text)
        except ValueError:
            return date.today()

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

    def _build_route_stop_payload(
        self,
        *,
        assignment: dict[str, str | bool | None],
        address: str,
        subject: str | None,
    ) -> dict[str, object]:
        sr_id = str(assignment.get("serviceRequestId") or "").strip()
        status = (
            assignment.get("status")
            or assignment.get("serviceRequestStatus")
            or assignment.get("service_request_status")
            or ("complete" if str(assignment.get("isComplete")).lower() in {"1", "true", "yes"} else "scheduled")
        )
        return {
            "id": str(assignment.get("assignmentId") or sr_id or ""),
            "label": f"SR-{sr_id}" if sr_id else "Service Request",
            "srId": sr_id or None,
            "service_request_id": sr_id or None,
            "address": address,
            "subject": subject or assignment.get("subject") or "Service Request",
            "customer_name": subject or assignment.get("subject") or "Service Request",
            "routeLabel": assignment.get("routeLabel") or assignment.get("window") or assignment.get("timeWindow"),
            "window_start": self._format_assignment_clock(assignment.get("start")),
            "window_end": self._format_assignment_clock(assignment.get("end")),
            "duration_minutes": 30,
            "status": str(status or "scheduled"),
            "lat": self._safe_float(assignment.get("lat")),
            "lon": self._safe_float(assignment.get("lon")),
        }

    def _normalize_route_stop_input(
        self,
        stop: dict[str, object],
        *,
        index: int,
        adhoc: bool = False,
    ) -> dict[str, object]:
        stop_id = str(stop.get("id") or stop.get("srId") or stop.get("service_request_id") or f"{'adhoc' if adhoc else 'stop'}-{index + 1}")
        label = str(stop.get("label") or stop.get("customer_name") or stop.get("subject") or f"Stop {index + 1}")
        return {
            "id": stop_id,
            "label": label,
            "srId": str(stop.get("srId") or stop.get("service_request_id") or "") or None,
            "service_request_id": str(stop.get("service_request_id") or stop.get("srId") or "") or None,
            "address": str(stop.get("address") or "").strip(),
            "subject": str(stop.get("subject") or stop.get("customer_name") or label),
            "customer_name": str(stop.get("customer_name") or stop.get("subject") or label),
            "routeLabel": str(stop.get("routeLabel") or stop.get("window") or "").strip() or None,
            "window_start": str(stop.get("window_start") or stop.get("windowStart") or "").strip() or None,
            "window_end": str(stop.get("window_end") or stop.get("windowEnd") or "").strip() or None,
            "duration_minutes": int(stop.get("duration_minutes") or stop.get("durationMinutes") or 30),
            "status": str(stop.get("status") or ("draft" if adhoc else "scheduled")),
            "lat": self._safe_float(stop.get("lat") or stop.get("latitude")),
            "lon": self._safe_float(stop.get("lon") or stop.get("lng") or stop.get("longitude")),
            "eta": str(stop.get("eta") or "").strip() or None,
        }

    def _format_assignment_clock(self, value: str | bool | None) -> str | None:
        rendered = self._format_assignment_time(value)
        if not rendered:
            return None
        for fmt in ("%I:%M %p", "%H:%M"):
            try:
                return datetime.strptime(rendered, fmt).strftime("%H:%M")
            except ValueError:
                continue
        return None

    def _status_meta(self, service_request_status: str | None) -> dict[str, object]:
        """Return status metadata even when the bluefolder service is a light stub in tests."""
        describe = getattr(self.bluefolder_service, "describe_service_request_status", None)
        if callable(describe):
            return describe(service_request_status)
        adapter = getattr(self.bluefolder_service, "adapter", None)
        return describe_service_request_status(service_request_status, base_path=getattr(adapter, "base_path", None))

    @staticmethod
    def _safe_float(value: object) -> float | None:
        try:
            parsed = float(value)  # type: ignore[arg-type]
        except Exception:
            return None
        return parsed if parsed == parsed else None

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
