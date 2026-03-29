"""Technician app-facing API service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ops_hub.models.requests import PartRequestCreate
from ops_hub.services.bluefolder import BlueFolderService
from ops_hub.services.operator_directory import TechnicianDirectoryService
from ops_hub.services.parts_cannon import PartsCannonService
from ops_hub.services.photo_ingest import PhotoIngestService

if TYPE_CHECKING:
    from ops_hub.services.workflow_state import WorkflowStateService


@dataclass(slots=True)
class TechnicianApiService:
    """Expose technician-friendly JSON-ready workflows."""

    bluefolder_service: BlueFolderService
    technician_directory_service: TechnicianDirectoryService
    parts_cannon_service: PartsCannonService
    photo_ingest_service: PhotoIngestService
    workflow_state_service: "WorkflowStateService"

    async def health(self) -> dict[str, object]:
        """Return a minimal health payload for app clients."""
        return {"ok": True, "service": "ops-hub", "api": "technician"}

    async def get_today(self, *, technician_bluefolder_user_id: int) -> list[dict[str, object]]:
        """Return today's assignments in the app's expected shape."""
        assignments = await self.bluefolder_service.get_assignments_for_user_today(technician_bluefolder_user_id)
        return [self._assignment_to_job(item) for item in assignments]

    async def get_jobs(
        self,
        *,
        technician_bluefolder_user_id: int,
        start: str | None,
        end: str | None,
        date_range_type: str,
    ) -> list[dict[str, object]]:
        """Return jobs for the current technician.

        For now this reuses today's assignment surface; the app can still narrow
        from its side while we keep the backend cutover small.
        """
        _ = (start, end, date_range_type)
        return await self.get_today(technician_bluefolder_user_id=technician_bluefolder_user_id)

    async def update_status(
        self,
        *,
        sr_id: int,
        technician_discord_user_id: int,
        status: str,
        technician_bluefolder_user_id: int | None,
    ) -> dict[str, object]:
        """Apply a technician status transition."""
        normalized = status.strip().casefold()
        if normalized == "enroute":
            result = await self.bluefolder_service.log_route_update(
                sr_id,
                update_type="enroute",
                requested_by_user_id=technician_discord_user_id,
                bluefolder_user_id=technician_bluefolder_user_id,
            )
        elif normalized == "arrive":
            result = await self.bluefolder_service.log_field_event(
                sr_id,
                event_type="arrive",
                requested_by_user_id=technician_discord_user_id,
                bluefolder_user_id=technician_bluefolder_user_id,
            )
        elif normalized == "complete":
            result = await self.bluefolder_service.log_field_event(
                sr_id,
                event_type="complete",
                requested_by_user_id=technician_discord_user_id,
                bluefolder_user_id=technician_bluefolder_user_id,
            )
        else:
            return {"success": False, "message": f"Unsupported technician status `{status}`."}
        return {"success": True, "message": result.message}

    async def submit_note(
        self,
        *,
        sr_id: int,
        note: str,
        technician_discord_user_id: int,
        technician_bluefolder_user_id: int | None,
    ) -> dict[str, object]:
        """Submit a field note to BlueFolder."""
        cleaned = " ".join((note or "").split()).strip()
        if not cleaned:
            return {"success": False, "message": "A note is required."}
        result = await self.bluefolder_service.log_field_event(
            sr_id,
            event_type="note",
            requested_by_user_id=technician_discord_user_id,
            bluefolder_user_id=technician_bluefolder_user_id,
            details=cleaned,
        )
        return {"success": True, "message": result.message}

    async def create_parts_request(
        self,
        *,
        sr_id: int,
        details: str,
        technician_discord_user_id: int,
        technician_bluefolder_user_id: int | None,
    ) -> dict[str, object]:
        """Create a tracked parts request for a technician."""
        cleaned = " ".join((details or "").split()).strip()
        if not cleaned:
            cleaned = "Requested from technician mobile workflow."
        result = await self.parts_cannon_service.create_request(
            PartRequestCreate(
                reference=f"SR-{sr_id}",
                description=cleaned,
                requested_by_user_id=technician_discord_user_id,
                technician_bluefolder_user_id=technician_bluefolder_user_id,
                requester_is_admin=False,
            )
        )
        return {"success": True, "message": result.message}

    async def prepare_photo_upload(
        self,
        *,
        sr_id: int,
        label: str,
    ) -> dict[str, object]:
        """Acknowledge the next photo handoff step for the mobile client."""
        normalized = " ".join((label or "").split()).strip() or "job photo"
        return {
            "success": True,
            "message": (
                f"Photo handoff prepared for SR-{sr_id} ({normalized}). "
                "Upload transport still depends on the configured archive/upload path."
            ),
        }

    def resolve_technician(self, *, token_subject: str | None = None, technician_id: str | None = None) -> tuple[int, int] | None:
        """Resolve Discord and BlueFolder IDs from the caller context."""
        resolved_discord = None
        if technician_id and technician_id.isdigit():
            resolved_discord = int(technician_id)
        elif token_subject and token_subject.isdigit():
            resolved_discord = int(token_subject)
        if resolved_discord is None:
            return None

        mappings = self.technician_directory_service.mappings()
        bluefolder_user_id = mappings.get(resolved_discord)
        if bluefolder_user_id is None:
            return None
        return resolved_discord, bluefolder_user_id

    async def get_job(self, *, sr_id: int) -> dict[str, object]:
        """Return a single job summary in the app shape."""
        summary = await self.bluefolder_service.get_job_summary(f"SR-{sr_id}")
        parts_case = await self.workflow_state_service.get_parts_case(sr_id=sr_id)
        if not summary.available:
            return {
                "id": str(sr_id),
                "address": "",
                "appointmentWindow": "Unscheduled",
                "customerName": "Unknown customer",
                "customerPhone": "",
                "status": summary.integration_status,
                "partsStage": parts_case.stage_label,
                "nextAction": parts_case.next_action or "",
                "equipment": None,
            }
        address = ", ".join(part for part in [summary.address, " ".join(v for v in [summary.city, summary.state, summary.postal_code] if v).strip()] if part)
        return {
            "id": str(summary.service_request_id or sr_id),
            "address": address,
            "appointmentWindow": "Scheduled",
            "customerName": summary.customer_name or "Unknown customer",
            "customerPhone": summary.customer_phone or "",
            "status": summary.service_request_status or "Unknown",
            "partsStage": parts_case.stage_label,
            "nextAction": parts_case.next_action or "",
            "equipment": None,
        }

    async def get_job_parts_case(self, *, sr_id: int) -> dict[str, object]:
        """Return the current derived parts-case payload for a service request."""
        case = await self.workflow_state_service.get_parts_case(sr_id=sr_id)
        return {
            "reference": case.reference,
            "stage": case.stage,
            "stageLabel": case.stage_label,
            "status": case.status,
            "openRequestIds": case.open_request_ids,
            "assignedPartsUserId": case.assigned_parts_user_id,
            "blocker": case.blocker,
            "latestStatusText": case.latest_status_text,
            "latestIssueText": case.latest_issue_text,
            "nextAction": case.next_action,
            "updatedAt": case.updated_at,
        }

    async def get_job_timeline(self, *, sr_id: int) -> list[dict[str, object]]:
        """Return the current merged SR timeline payload."""
        timeline = await self.workflow_state_service.build_service_request_timeline(sr_id)
        return [
            {
                "occurredAt": entry.occurred_at,
                "source": entry.source,
                "eventType": entry.event_type,
                "summary": entry.summary,
                "details": entry.details,
                "actorLabel": entry.actor_label,
            }
            for entry in timeline.entries
        ]

    @staticmethod
    def _assignment_to_job(item: dict[str, object]) -> dict[str, object]:
        """Normalize an assignment into the Android app's job payload."""
        return {
            "id": str(item.get("serviceRequestId") or item.get("id") or ""),
            "address": str(item.get("address") or ""),
            "appointmentWindow": str(item.get("timeWindow") or item.get("appointmentWindow") or "Unscheduled"),
            "customerName": str(item.get("customerName") or item.get("subject") or "Unknown customer"),
            "customerPhone": str(item.get("customerPhone") or ""),
            "status": str(item.get("status") or "Pending"),
            "distanceMiles": item.get("distanceMiles"),
            "equipment": item.get("equipment"),
        }
