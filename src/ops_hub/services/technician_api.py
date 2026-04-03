"""Technician app-facing API service."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ops_hub.models.requests import PartRequestCreate, PhotoAttachmentPayload
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
        elif normalized == "start":
            result = await self.bluefolder_service.log_field_event(
                sr_id,
                event_type="start",
                requested_by_user_id=technician_discord_user_id,
                bluefolder_user_id=technician_bluefolder_user_id,
                notify_dispatch=True,
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

    async def upload_job_photo(
        self,
        *,
        sr_id: int,
        label: str,
        filename: str,
        content_type: str | None,
        data_base64: str,
        technician_discord_user_id: int,
    ) -> dict[str, object]:
        """Attach one app-captured photo directly to the service request."""
        cleaned_label = " ".join((label or "").split()).strip() or "job photo"
        cleaned_filename = " ".join((filename or "").split()).strip() or f"sr-{sr_id}-{cleaned_label}.jpg"
        cleaned_content_type = " ".join((content_type or "").split()).strip() or "image/jpeg"
        if not data_base64.strip():
            return {"success": False, "message": "Photo data is required."}
        try:
            photo_bytes = base64.b64decode(data_base64.encode("utf-8"), validate=True)
        except (ValueError, binascii.Error):
            return {"success": False, "message": "Photo data was not valid base64."}
        result = await self.photo_ingest_service.attach_job_photo(
            sr_id,
            photo=PhotoAttachmentPayload(
                filename=cleaned_filename,
                content_type=cleaned_content_type,
                data=photo_bytes,
            ),
            requested_by_user_id=technician_discord_user_id,
            requested_by_label=f"Tech {technician_discord_user_id}",
            label=cleaned_label.upper(),
        )
        return {"success": True, "message": result.message}

    async def log_call_ahead(
        self,
        *,
        sr_id: int,
        technician_discord_user_id: int,
        technician_bluefolder_user_id: int | None,
        minutes: int | None = None,
    ) -> dict[str, object]:
        """Record a customer call-ahead as an ETA-driven field update."""
        eta_minutes = minutes if minutes is not None and minutes > 0 else 30
        result = await self.bluefolder_service.log_route_update(
            sr_id,
            update_type="eta",
            requested_by_user_id=technician_discord_user_id,
            bluefolder_user_id=technician_bluefolder_user_id,
            minutes=eta_minutes,
            notify_dispatch=True,
        )
        return {
            "success": True,
            "message": result.message,
            "callAheadMinutes": eta_minutes,
        }

    async def log_work_start(
        self,
        *,
        sr_id: int,
        technician_discord_user_id: int,
        technician_bluefolder_user_id: int | None,
        details: str | None = None,
    ) -> dict[str, object]:
        """Record a structured work-start event."""
        result = await self.bluefolder_service.log_field_event(
            sr_id,
            event_type="start",
            requested_by_user_id=technician_discord_user_id,
            bluefolder_user_id=technician_bluefolder_user_id,
            details=" ".join((details or "").split()).strip() or None,
            notify_dispatch=True,
        )
        return {"success": True, "message": result.message}

    async def report_no_answer(
        self,
        *,
        sr_id: int,
        details: str,
        technician_discord_user_id: int,
        technician_bluefolder_user_id: int | None,
    ) -> dict[str, object]:
        """Record a no-answer field exception for dispatch follow-up."""
        result = await self.bluefolder_service.log_field_event(
            sr_id,
            event_type="no_answer",
            requested_by_user_id=technician_discord_user_id,
            bluefolder_user_id=technician_bluefolder_user_id,
            details=" ".join((details or "").split()).strip() or None,
            notify_dispatch=True,
        )
        return {"success": True, "message": result.message}

    async def report_not_home(
        self,
        *,
        sr_id: int,
        details: str,
        technician_discord_user_id: int,
        technician_bluefolder_user_id: int | None,
    ) -> dict[str, object]:
        """Record a not-home field exception for dispatch follow-up."""
        result = await self.bluefolder_service.log_field_event(
            sr_id,
            event_type="not_home",
            requested_by_user_id=technician_discord_user_id,
            bluefolder_user_id=technician_bluefolder_user_id,
            details=" ".join((details or "").split()).strip() or None,
            notify_dispatch=True,
        )
        return {"success": True, "message": result.message}

    async def report_quote_needed(
        self,
        *,
        sr_id: int,
        details: str,
        technician_discord_user_id: int,
        technician_bluefolder_user_id: int | None,
        subtype: str | None = None,
    ) -> dict[str, object]:
        """Record a structured quote-needed handoff for office follow-up."""
        cleaned = " ".join((details or "").split()).strip()
        quote_subtype = self._normalize_quote_subtype(subtype)
        note_bits = ["Quote needed"]
        if quote_subtype != "customer":
            note_bits.append(f"({quote_subtype})")
        if cleaned:
            note_bits.append(f"- {cleaned}")
        result = await self.bluefolder_service.log_field_event(
            sr_id,
            event_type="note",
            requested_by_user_id=technician_discord_user_id,
            bluefolder_user_id=technician_bluefolder_user_id,
            details=" ".join(note_bits),
            notify_dispatch=True,
        )
        self.workflow_state_service.record_event(
            event_type="quote_needed_reported",
            source="ops_hub.field",
            sr_id=sr_id,
            summary=f"Technician reported quote-needed follow-up for SR-{sr_id}.",
            actor_user_id=technician_discord_user_id,
            details=cleaned or None,
            metadata={"quote_subtype": quote_subtype},
        )
        return {
            "success": True,
            "message": result.message,
            "quoteSubtype": quote_subtype,
        }

    async def report_reschedule_needed(
        self,
        *,
        sr_id: int,
        reason: str,
        technician_discord_user_id: int,
        technician_bluefolder_user_id: int | None,
    ) -> dict[str, object]:
        """Record a reschedule-needed handoff for dispatch."""
        cleaned = " ".join((reason or "").split()).strip()
        if not cleaned:
            return {"success": False, "message": "A reschedule reason is required."}
        result = await self.bluefolder_service.log_field_event(
            sr_id,
            event_type="reschedule_needed",
            requested_by_user_id=technician_discord_user_id,
            bluefolder_user_id=technician_bluefolder_user_id,
            details=cleaned,
            notify_dispatch=True,
        )
        return {"success": True, "message": result.message}

    async def report_unable_to_complete(
        self,
        *,
        sr_id: int,
        reason: str,
        technician_discord_user_id: int,
        technician_bluefolder_user_id: int | None,
    ) -> dict[str, object]:
        """Record a structured unable-to-complete handoff."""
        cleaned = " ".join((reason or "").split()).strip()
        if not cleaned:
            return {"success": False, "message": "A closeout reason is required."}
        result = await self.bluefolder_service.log_field_event(
            sr_id,
            event_type="unable_to_complete",
            requested_by_user_id=technician_discord_user_id,
            bluefolder_user_id=technician_bluefolder_user_id,
            details=cleaned,
            notify_dispatch=True,
        )
        self.workflow_state_service.record_event(
            event_type="unable_to_complete_reported",
            source="ops_hub.field",
            sr_id=sr_id,
            summary=f"Technician reported unable-to-complete for SR-{sr_id}.",
            actor_user_id=technician_discord_user_id,
            details=cleaned,
        )
        return {"success": True, "message": result.message}

    async def get_job_photo_status(self, *, sr_id: int) -> dict[str, object]:
        """Return structured photo-compliance state for a service request."""
        if not self.photo_ingest_service.feature_flags.is_enabled("photo_mailbox_scan"):
            return {
                "enabled": False,
                "srId": sr_id,
                "mailboxStatus": "disabled",
                "message": "Photo mailbox scan is currently disabled.",
                "totalPhotos": 0,
                "foundTags": [],
                "missingTags": [],
                "records": [],
                "shouldNotify": False,
                "reason": "Photo mailbox scan is disabled.",
            }

        summary = await self.photo_ingest_service.adapter.get_photo_compliance_summary(sr_id)
        reminder = await self.photo_ingest_service.evaluate_photo_reminder(sr_id, send_notice=False)
        return {
            "enabled": True,
            "srId": sr_id,
            "mailboxStatus": summary.mailbox_status,
            "message": summary.message,
            "totalPhotos": summary.total_photos,
            "foundTags": summary.found_tags,
            "missingTags": summary.missing_tags,
            "records": [
                {
                    "subject": record.subject,
                    "fromEmail": record.from_email,
                    "receivedAt": record.received_at,
                    "attachmentCount": record.attachment_count,
                    "attachmentNames": record.attachment_names,
                }
                for record in summary.matched_records
            ],
            "shouldNotify": "Should notify: `yes`" in reminder.message,
            "reason": self._extract_photo_reminder_reason(reminder.message),
        }

    async def evaluate_job_photo_compliance(
        self,
        *,
        sr_id: int,
        status_override: str | None = None,
        send_notice: bool = False,
    ) -> dict[str, object]:
        """Evaluate photo reminder state in a client-friendly shape."""
        result = await self.photo_ingest_service.evaluate_photo_reminder(
            sr_id,
            status_override=status_override,
            send_notice=send_notice,
        )
        return {
            "success": True,
            "srId": sr_id,
            "message": result.message,
            "shouldNotify": "Should notify: `yes`" in result.message,
            "reason": self._extract_photo_reminder_reason(result.message),
            "noticeRequested": send_notice,
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

    @staticmethod
    def _normalize_quote_subtype(subtype: str | None) -> str:
        normalized = str(subtype or "").strip().casefold().replace(" ", "_").replace("-", "_")
        if normalized in {"landlord", "tenant"}:
            return "landlord"
        if normalized in {"prepayment", "prepay", "cod"}:
            return "prepayment"
        return "customer"

    @staticmethod
    def _extract_photo_reminder_reason(message: str) -> str:
        for line in message.splitlines():
            if line.startswith("Reason: "):
                return line.removeprefix("Reason: ").strip()
        return message.strip()
