"""Parts handoff and tracked-request service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ops_hub.integrations.parts_cannon_adapter import PartsHandoffAdapter
from ops_hub.models.requests import (
    CommandResult,
    PartLookupRequest,
    PartRequestClaim,
    PartRequestCreate,
    PartRequestRecord,
    PartsRequestQueueSummary,
    PartRequestUpdate,
    PartsWorkflowSummary,
)
from ops_hub.services.notifications import NotificationService
from ops_hub.services.operator_directory import TechnicianDirectoryService
from ops_hub.services.bluefolder_status_catalog import describe_service_request_status, status_catalog_payload
from ops_hub.services.parts_request_store import PartsRequestStore
from ops_hub.services.text_blocks import section, status_section

if TYPE_CHECKING:
    from ops_hub.services.workflow_state import WorkflowStateService

PARTS_REQUEST_STATUSES: tuple[str, ...] = (
    "requested",
    "ordered",
    "received",
    "resolved",
    "cancelled",
)


@dataclass(slots=True)
class PartsHandoffService:
    """Parts workflow service facade with optional downstream handoff support."""

    adapter: PartsHandoffAdapter
    notifications: NotificationService
    request_store: PartsRequestStore
    technician_directory_service: TechnicianDirectoryService | None = None
    workflow_state_service: "WorkflowStateService | None" = None

    async def lookup_part(self, request: PartLookupRequest) -> CommandResult:
        """Return the current parts-system and local queue state for a reference."""
        result = await self.adapter.get_part_status(request.reference)
        matching_records = self._matching_records_for_reference(request.reference)
        await self.notifications.send_notice(
            topic="parts.lookup",
            message=f"Parts lookup requested for {request.reference} with status {result.integration_status}.",
        )
        notification_status = await self.notifications.status()
        return self._build_lookup_result(request, result, notification_status.mode, matching_records)

    async def create_request(self, request: PartRequestCreate) -> CommandResult:
        """Create a lightweight parts request record."""
        records = self.request_store.load()
        request_id = max((record.request_id for record in records), default=0) + 1
        timestamp = datetime.now(UTC).isoformat(timespec="seconds")
        record = PartRequestRecord(
            request_id=request_id,
            reference=request.reference,
            description=request.description,
            requested_by_user_id=request.requested_by_user_id,
            technician_bluefolder_user_id=request.technician_bluefolder_user_id,
            assigned_parts_user_id=None,
            status="requested",
            created_at=timestamp,
            updated_at=timestamp,
            last_synced_at=None,
            last_reconciled_at=None,
            downstream_note=None,
        )
        records.append(record)
        self.request_store.save(records)
        if self.workflow_state_service is not None:
            self.workflow_state_service.record_event(
                event_type="parts_request_created",
                source="ops_hub.parts_queue",
                reference=record.reference,
                sr_id=self._reference_sr_id(record.reference),
                actor_user_id=record.requested_by_user_id,
                summary=f"Created tracked parts request {record.request_id} for {record.reference}.",
                details=record.description,
                occurred_at=record.created_at,
            )
        await self.notifications.send_notice(
            topic="parts.request.created",
            message=f"Created parts request {request_id} for {request.reference}.",
        )
        return CommandResult(
            message="\n".join(
                [
                    f"**Parts Request {request_id} Created**",
                    f"Reference: `{record.reference}`",
                    f"Status: `{record.status}`",
                    f"Requested by: {self._discord_user_label(record.requested_by_user_id)}",
                    f"Description: {record.description}",
                ]
            )
        )

    async def list_requests(
        self,
        *,
        status: str | None = None,
        requested_by_user_id: int | None = None,
        only_unsynced: bool = False,
    ) -> CommandResult:
        """List current parts requests, optionally filtered by status or requester."""
        normalized_status = None if status is None else self._normalize_status(status)
        if status is not None and normalized_status is None:
            return CommandResult(
                message=(
                    "Invalid parts request status. "
                    f"Allowed values: {', '.join(f'`{value}`' for value in PARTS_REQUEST_STATUSES)}."
                )
            )

        records = self.request_store.load()
        if normalized_status is not None:
            records = [record for record in records if record.status == normalized_status]
        if requested_by_user_id is not None:
            records = [record for record in records if record.requested_by_user_id == requested_by_user_id]
        if only_unsynced:
            records = [record for record in records if record.last_synced_at is None and record.status not in {"resolved", "cancelled"}]

        if not records:
            return CommandResult(message="No parts requests found.")

        lines = ["**Parts Requests**"]
        records_by_reference: dict[str, list[PartRequestRecord]] = {}
        for record in records:
            records_by_reference.setdefault(record.reference, []).append(record)

        grouped_items = list(sorted(records_by_reference.items()))[:15]
        for reference, grouped_records in grouped_items:
            case = await self._parts_case_for_reference(reference)
            lines.extend(
                [
                    "",
                    f"`{reference}` `{case.stage_label}` `{case.status}`",
                ]
            )
            if case.open_request_ids:
                lines.append("Tracked requests: " + ", ".join(f"`{request_id}`" for request_id in case.open_request_ids))
            if case.assigned_parts_user_id is not None:
                lines.append(f"Assigned to: {self._discord_user_label(case.assigned_parts_user_id)}")
            if case.next_action:
                lines.append(f"Next action: {case.next_action}")
            if case.blocker:
                lines.append(f"Blocker: {case.blocker}")

            for record in grouped_records[:3]:
                lines.append(
                    f"Request `{record.request_id}` `{record.status}` requested by {self._discord_user_label(record.requested_by_user_id)}"
                )
                if record.last_synced_at is not None:
                    lines.append(f"Last synced: `{record.last_synced_at}`")
                lines.append(f"Description: {record.description}")
            if len(grouped_records) > 3:
                lines.append(f"...and {len(grouped_records) - 3} more tracked request(s)")

        if len(records_by_reference) > 15:
            lines.extend(["", f"...and {len(records_by_reference) - 15} more reference group(s)"])
        return CommandResult(message="\n".join(lines))

    async def update_request(self, request: PartRequestUpdate) -> CommandResult:
        """Update the status of an existing parts request."""
        normalized_status = self._normalize_status(request.status)
        if normalized_status is None:
            return CommandResult(
                message=(
                    "Invalid parts request status. "
                    f"Allowed values: {', '.join(f'`{value}`' for value in PARTS_REQUEST_STATUSES)}."
                )
            )

        records = self.request_store.load()
        for index, record in enumerate(records):
            if record.request_id != request.request_id:
                continue

            updated = PartRequestRecord(
                request_id=record.request_id,
                reference=record.reference,
                description=record.description,
                requested_by_user_id=record.requested_by_user_id,
                technician_bluefolder_user_id=record.technician_bluefolder_user_id,
                assigned_parts_user_id=record.assigned_parts_user_id,
                status=normalized_status,
                created_at=record.created_at,
                updated_at=datetime.now(UTC).isoformat(timespec="seconds"),
                last_synced_at=record.last_synced_at,
                last_reconciled_at=record.last_reconciled_at,
                downstream_note=record.downstream_note,
            )
            records[index] = updated
            self.request_store.save(records)
            if self.workflow_state_service is not None:
                self.workflow_state_service.record_event(
                    event_type=f"parts_request_{normalized_status}",
                    source="ops_hub.parts_queue",
                    reference=updated.reference,
                    sr_id=self._reference_sr_id(updated.reference),
                    actor_user_id=request.updated_by_user_id,
                    summary=f"Updated tracked parts request {updated.request_id} to {updated.status}.",
                    occurred_at=updated.updated_at,
                )
            await self.notifications.send_notice(
                topic="parts.request.updated",
                message=f"Updated parts request {request.request_id} to {request.status}.",
            )
            return CommandResult(
                message="\n".join(
                    [
                        f"**Parts Request {updated.request_id} Updated**",
                        f"Reference: `{updated.reference}`",
                        f"Status: `{updated.status}`",
                    ]
                )
            )

        return CommandResult(message=f"Parts request `{request.request_id}` was not found.")

    async def get_request(self, request_id: int) -> CommandResult:
        """Return a detailed view of a tracked parts request."""
        record = self._find_record(request_id)
        if record is None:
            return CommandResult(message=f"Parts request `{request_id}` was not found.")

        case = await self._parts_case_for_reference(record.reference)
        lines = [
            f"**Parts Request {record.request_id}**",
            f"Reference: `{record.reference}`",
            f"Tracked status: `{record.status}`",
            "",
            "**Parts Case**",
            f"Case stage: `{case.stage_label}`",
            f"Case status: `{case.status}`",
        ]
        if case.open_request_ids:
            lines.append("Open tracked requests: " + ", ".join(f"`{item}`" for item in case.open_request_ids))
        if case.assigned_parts_user_id is not None:
            lines.append(f"Assigned parts owner: {self._discord_user_label(case.assigned_parts_user_id)}")
        if case.next_action:
            lines.append(f"Next action: {case.next_action}")
        if case.blocker:
            lines.append(f"Blocker: {case.blocker}")
        if case.latest_status_text:
            lines.append(f"Latest status: {case.latest_status_text}")

        lines.extend(
            [
                "",
                "**People**",
                f"Requested by: {self._discord_user_label(record.requested_by_user_id)}",
                (
                    f"Assigned to: {self._discord_user_label(record.assigned_parts_user_id)}"
                    if record.assigned_parts_user_id is not None
                    else "Assigned to: unassigned"
                ),
                "",
                "**Tracking**",
                f"Created at: `{record.created_at}`",
                f"Updated at: `{record.updated_at}`",
                f"Last synced: `{record.last_synced_at}`" if record.last_synced_at is not None else "Last synced: never",
                f"Last reconciled: `{record.last_reconciled_at}`" if record.last_reconciled_at is not None else "Last reconciled: never",
                "",
                "**Request**",
                f"Description: {record.description}",
            ]
        )
        if record.technician_bluefolder_user_id is not None:
            lines.append(f"Technician mapping: {self._technician_mapping_label(record)}")
        if record.downstream_note:
            lines.append("")
            lines.append(f"Downstream note: {record.downstream_note}")
        return CommandResult(message="\n".join(lines))

    async def claim_request(self, request: PartRequestClaim) -> CommandResult:
        """Assign or unassign a parts request."""
        records = self.request_store.load()
        for index, record in enumerate(records):
            if record.request_id != request.request_id:
                continue

            updated = PartRequestRecord(
                request_id=record.request_id,
                reference=record.reference,
                description=record.description,
                requested_by_user_id=record.requested_by_user_id,
                technician_bluefolder_user_id=record.technician_bluefolder_user_id,
                assigned_parts_user_id=request.parts_user_id,
                status=record.status,
                created_at=record.created_at,
                updated_at=datetime.now(UTC).isoformat(timespec="seconds"),
                last_synced_at=record.last_synced_at,
                last_reconciled_at=record.last_reconciled_at,
                downstream_note=record.downstream_note,
            )
            records[index] = updated
            self.request_store.save(records)
            if self.workflow_state_service is not None:
                self.workflow_state_service.record_event(
                    event_type="parts_request_claimed" if request.parts_user_id is not None else "parts_request_unclaimed",
                    source="ops_hub.parts_queue",
                    reference=updated.reference,
                    sr_id=self._reference_sr_id(updated.reference),
                    actor_user_id=request.updated_by_user_id,
                    summary=(
                        f"Assigned tracked parts request {updated.request_id}."
                        if request.parts_user_id is not None
                        else f"Cleared assignment for tracked parts request {updated.request_id}."
                    ),
                    details=(
                        f"assigned_parts_user_id={request.parts_user_id}"
                        if request.parts_user_id is not None
                        else None
                    ),
                    occurred_at=updated.updated_at,
                )
            if request.parts_user_id is None:
                topic = "parts.request.unclaimed"
                message = f"Unassigned parts request {request.request_id}."
                response = f"**Parts Request {updated.request_id}**\nAssignment cleared."
            else:
                topic = "parts.request.claimed"
                message = f"Assigned parts request {request.request_id} to parts user {request.parts_user_id}."
                response = (
                    f"**Parts Request {updated.request_id}**\n"
                    f"Assigned to: {self._discord_user_label(request.parts_user_id)}"
                )
            await self.notifications.send_notice(topic=topic, message=message)
            return CommandResult(
                message="\n".join(
                    [
                        response,
                        f"Reference: `{updated.reference}`",
                        f"Status: `{updated.status}`",
                    ]
                )
            )

        return CommandResult(message=f"Parts request `{request.request_id}` was not found.")

    async def sync_requests_to_parts_system(self) -> CommandResult:
        """Export the tracked request queue to the configured parts workflow path."""
        records = self.request_store.load()
        exportable_records = [record for record in records if record.status not in {"resolved", "cancelled"}]
        export_result = await self.adapter.export_requests(exportable_records)
        synced_at = datetime.now(UTC).isoformat(timespec="seconds")
        if export_result.integration_status == "exported":
            synced_ids = {record.request_id for record in exportable_records}
            updated_records = [
                PartRequestRecord(
                    request_id=record.request_id,
                    reference=record.reference,
                    description=record.description,
                    requested_by_user_id=record.requested_by_user_id,
                    technician_bluefolder_user_id=record.technician_bluefolder_user_id,
                    assigned_parts_user_id=record.assigned_parts_user_id,
                    status=record.status,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                    last_synced_at=synced_at if record.request_id in synced_ids else record.last_synced_at,
                    last_reconciled_at=record.last_reconciled_at,
                    downstream_note=record.downstream_note,
                )
                for record in records
            ]
            self.request_store.save(updated_records)
        await self.notifications.send_notice(
            topic="parts.request.sync",
            message=f"Parts queue sync finished with status {export_result.integration_status}.",
        )
        lines = [
            "**Parts Queue Sync**",
        ]
        lines.extend(
            status_section(
                "",
                status=export_result.integration_status,
                details=export_result.message,
                extra_lines=[f"Exported requests: `{export_result.exported_count}`"],
            )[1:]
        )
        if export_result.integration_status == "exported":
            lines.append(f"Synced at: `{synced_at}`")
        if export_result.export_path is not None:
            lines.append(f"Export path: `{export_result.export_path}`")
        return CommandResult(message="\n".join(lines))

    async def reconcile_requests_from_parts_system(self) -> CommandResult:
        """Apply downstream receipt updates back onto tracked parts requests."""
        import_result = await self.adapter.import_receipts()
        records = self.request_store.load()
        receipts = import_result.receipts or []
        applied = 0
        ignored = 0
        reconciled_at = datetime.now(UTC).isoformat(timespec="seconds")
        indexed = {record.request_id: record for record in records}
        updated_records: list[PartRequestRecord] = []
        updates: dict[int, PartRequestRecord] = {}

        if import_result.integration_status == "imported":
            for receipt in receipts:
                normalized_status = self._normalize_status(receipt.status)
                existing = indexed.get(receipt.request_id)
                if normalized_status is None or existing is None:
                    ignored += 1
                    continue
                applied += 1
                updates[receipt.request_id] = PartRequestRecord(
                    request_id=existing.request_id,
                    reference=existing.reference,
                    description=existing.description,
                    requested_by_user_id=existing.requested_by_user_id,
                    technician_bluefolder_user_id=existing.technician_bluefolder_user_id,
                    assigned_parts_user_id=existing.assigned_parts_user_id,
                    status=normalized_status,
                    created_at=existing.created_at,
                    updated_at=reconciled_at,
                    last_synced_at=existing.last_synced_at,
                    last_reconciled_at=reconciled_at,
                    downstream_note=receipt.note,
                )

            updated_records = [updates.get(record.request_id, record) for record in records]
            if applied:
                self.request_store.save(updated_records)

        await self.notifications.send_notice(
            topic="parts.request.reconcile",
            message=f"Parts queue reconcile finished with status {import_result.integration_status}.",
        )
        lines = [
            "**Parts Queue Reconcile**",
        ]
        lines.extend(
            status_section(
                "",
                status=import_result.integration_status,
                details=import_result.message,
                extra_lines=[
                    f"Applied receipts: `{applied}`",
                    f"Ignored receipts: `{ignored}`",
                ],
            )[1:]
        )
        if import_result.receipt_path is not None:
            lines.append(f"Receipt path: `{import_result.receipt_path}`")
        return CommandResult(message="\n".join(lines))

    def supported_request_statuses(self) -> tuple[str, ...]:
        """Return the supported parts request statuses."""
        return PARTS_REQUEST_STATUSES

    def queue_summary(self) -> PartsRequestQueueSummary:
        """Return a concise summary of the tracked parts request queue."""
        records = self.request_store.load()
        counts = {status: 0 for status in PARTS_REQUEST_STATUSES}
        assigned_requests = 0
        open_requests = 0
        synced_requests = 0
        for record in records:
            counts[record.status] = counts.get(record.status, 0) + 1
            if record.assigned_parts_user_id is not None:
                assigned_requests += 1
            if record.last_synced_at is not None:
                synced_requests += 1
            if record.status not in {"resolved", "cancelled"}:
                open_requests += 1

        return PartsRequestQueueSummary(
            total_requests=len(records),
            open_requests=open_requests,
            assigned_requests=assigned_requests,
            unassigned_requests=max(len(records) - assigned_requests, 0),
            synced_requests=synced_requests,
            requested_count=counts["requested"],
            ordered_count=counts["ordered"],
            received_count=counts["received"],
            resolved_count=counts["resolved"],
            cancelled_count=counts["cancelled"],
        )

    async def get_parts_board_payload(self) -> dict[str, object]:
        """Return a structured parts-board payload for frontend clients."""
        queue_summary = self.queue_summary()
        cases = await self._current_parts_cases()
        open_cases = [case for case in cases if case.status == "open"]
        case_metrics = self._parts_case_metrics(cases)
        open_requests = [
            await self._record_payload(record)
            for record in self.request_store.load()
            if record.status not in {"resolved", "cancelled"}
        ]
        return {
            "queueSummary": self._queue_summary_payload(queue_summary),
            "caseMetrics": case_metrics,
            "openCases": [await self._parts_case_payload(case) for case in open_cases[:20]],
            "openTrackedRequests": open_requests[:20],
            "supportedRequestStatuses": list(PARTS_REQUEST_STATUSES),
            "serviceRequestStatusCatalog": status_catalog_payload(base_path=self._bluefolder_base_path()),
        }

    async def get_parts_cases_payload(
        self,
        *,
        stage: str | None = None,
        age: str | None = None,
        assigned_parts_user_id: int | None = None,
        status: str | None = None,
        reference: str | None = None,
    ) -> dict[str, object]:
        """Return structured parts-case list payload."""
        normalized_stage = None if stage is None else stage.strip().lower().replace(" ", "_")
        normalized_age = None if age is None else age.strip().lower().replace(" ", "_")
        normalized_status = None if status is None else status.strip().lower()
        normalized_reference = None if reference is None else reference.strip().upper()

        cases = await self._current_parts_cases()
        if normalized_stage is not None:
            cases = [case for case in cases if case.stage == normalized_stage]
        if normalized_age is not None:
            cases = [case for case in cases if case.age_bucket == normalized_age]
        if assigned_parts_user_id is not None:
            cases = [case for case in cases if case.assigned_parts_user_id == assigned_parts_user_id]
        if normalized_status is not None:
            cases = [case for case in cases if case.status == normalized_status]
        if normalized_reference is not None:
            cases = [case for case in cases if case.reference.upper() == normalized_reference]
        return {
            "filters": {
                "stage": normalized_stage,
                "age": normalized_age,
                "assignedPartsUserId": assigned_parts_user_id,
                "status": normalized_status,
                "reference": normalized_reference,
            },
            "items": [await self._parts_case_payload(case) for case in cases],
        }

    async def get_parts_case_payload(self, *, reference: str) -> dict[str, object]:
        """Return one parts case plus its tracked requests."""
        case = await self._parts_case_for_reference(reference.strip())
        matching_records = self._matching_records_for_reference(case.reference)
        return {
            "case": await self._parts_case_payload(case),
            "trackedRequests": [await self._record_payload(record) for record in matching_records],
        }

    async def get_parts_case_timeline_payload(self, *, reference: str) -> dict[str, object]:
        """Return workflow timeline for one parts case reference."""
        case = await self._parts_case_for_reference(reference.strip())
        if self.workflow_state_service is None:
            return {
                "reference": case.reference,
                "srId": case.sr_id,
                "entries": [],
            }

        if case.sr_id is not None:
            timeline = await self.workflow_state_service.build_service_request_timeline(case.sr_id)
            entries = [
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
            return {
                "reference": timeline.reference,
                "srId": timeline.sr_id,
                "entries": entries,
            }

        snapshot = self.workflow_state_service.current_snapshot()
        normalized_reference = case.reference.strip().casefold()
        events = [
            event
            for event in snapshot.events
            if (event.reference or "").strip().casefold() == normalized_reference
        ]
        events.sort(key=lambda item: item.occurred_at, reverse=True)
        return {
            "reference": case.reference,
            "srId": None,
            "entries": [
                {
                    "occurredAt": event.occurred_at,
                    "source": event.source,
                    "eventType": event.event_type,
                    "summary": event.summary,
                    "details": event.details,
                    "actorLabel": event.actor_label,
                }
                for event in events[:50]
            ],
        }

    async def get_parts_requests_payload(
        self,
        *,
        status: str | None = None,
        assigned_parts_user_id: int | None = None,
        requested_by_user_id: int | None = None,
        reference: str | None = None,
        only_unsynced: bool = False,
    ) -> dict[str, object]:
        """Return structured tracked-request list payload."""
        normalized_status = None if status is None else self._normalize_status(status)
        normalized_reference = None if reference is None else reference.strip().upper()
        records = self.request_store.load()
        if normalized_status is not None:
            records = [record for record in records if record.status == normalized_status]
        if assigned_parts_user_id is not None:
            records = [record for record in records if record.assigned_parts_user_id == assigned_parts_user_id]
        if requested_by_user_id is not None:
            records = [record for record in records if record.requested_by_user_id == requested_by_user_id]
        if normalized_reference is not None:
            records = [record for record in records if record.reference.strip().upper() == normalized_reference]
        if only_unsynced:
            records = [
                record
                for record in records
                if record.last_synced_at is None and record.status not in {"resolved", "cancelled"}
            ]
        return {
            "filters": {
                "status": normalized_status,
                "assignedPartsUserId": assigned_parts_user_id,
                "requestedByUserId": requested_by_user_id,
                "reference": normalized_reference,
                "onlyUnsynced": only_unsynced,
            },
            "items": [await self._record_payload(record) for record in records],
        }

    async def get_parts_request_payload(self, *, request_id: int) -> dict[str, object]:
        """Return one tracked request plus its derived case."""
        record = self._find_record(request_id)
        if record is None:
            raise ValueError(f"Parts request `{request_id}` was not found.")
        case = await self._parts_case_for_reference(record.reference)
        return {
            "request": await self._record_payload(record),
            "case": await self._parts_case_payload(case),
        }

    async def claim_request_payload(self, *, request_id: int, parts_user_id: int | None, actor_user_id: int) -> dict[str, object]:
        """Assign or clear a tracked request and return the updated payload."""
        result = await self.claim_request(
            PartRequestClaim(
                request_id=request_id,
                parts_user_id=parts_user_id,
                updated_by_user_id=actor_user_id,
            )
        )
        record = self._find_record(request_id)
        if record is None:
            raise ValueError(f"Parts request `{request_id}` was not found.")
        return {
            "success": True,
            "message": result.message,
            "request": await self._record_payload(record),
        }

    async def update_request_payload(self, *, request_id: int, status: str, actor_user_id: int) -> dict[str, object]:
        """Update a tracked request status and return the updated payload."""
        result = await self.update_request(
            PartRequestUpdate(
                request_id=request_id,
                status=status,
                updated_by_user_id=actor_user_id,
            )
        )
        record = self._find_record(request_id)
        if record is None:
            raise ValueError(f"Parts request `{request_id}` was not found.")
        return {
            "success": True,
            "message": result.message,
            "request": await self._record_payload(record),
        }

    async def sync_requests_payload(self) -> dict[str, object]:
        """Run queue export and return a structured response."""
        result = await self.sync_requests_to_parts_system()
        return {
            "success": True,
            "message": result.message,
            "queueSummary": self._queue_summary_payload(self.queue_summary()),
        }

    async def reconcile_requests_payload(self) -> dict[str, object]:
        """Run queue reconcile and return a structured response."""
        result = await self.reconcile_requests_from_parts_system()
        return {
            "success": True,
            "message": result.message,
            "queueSummary": self._queue_summary_payload(self.queue_summary()),
        }

    def _normalize_status(self, status: str) -> str | None:
        """Normalize a requested parts status and reject unsupported values."""
        candidate = status.strip().lower()
        if candidate in PARTS_REQUEST_STATUSES:
            return candidate
        return None

    def _find_record(self, request_id: int) -> PartRequestRecord | None:
        """Find a stored parts request record by id."""
        for record in self.request_store.load():
            if record.request_id == request_id:
                return record
        return None

    def _matching_records_for_reference(self, reference: str) -> list[PartRequestRecord]:
        """Return tracked parts requests whose reference matches the lookup."""
        normalized_reference = reference.strip().casefold()
        return [
            record
            for record in self.request_store.load()
            if record.reference.strip().casefold() == normalized_reference
        ]

    async def _parts_case_for_reference(self, reference: str):
        """Return a derived parts case for a reference."""
        if self.workflow_state_service is not None:
            return await self.workflow_state_service.get_parts_case(reference=reference)

        open_request_ids = [
            record.request_id
            for record in self._matching_records_for_reference(reference)
            if record.status not in {"resolved", "cancelled"}
        ]
        return type(
            "FallbackPartsCase",
            (),
            {
                "case_id": f"parts:{reference.strip().upper()}",
                "reference": reference,
                "sr_id": self._reference_sr_id(reference),
                "stage": "tracked_requests_only",
                "stage_label": "Tracked Requests Only",
                "status": "open" if open_request_ids else "inactive",
                "open_request_ids": open_request_ids,
                "assigned_parts_user_id": None,
                "requested_by_user_id": None,
                "technician_bluefolder_user_id": None,
                "next_action": "Review the tracked request and confirm the next parts step.",
                "blocker": None,
                "latest_status_text": None,
                "latest_issue_text": None,
                "updated_at": None,
                "age_hours": None,
                "age_bucket": None,
            },
        )()

    async def _current_parts_cases(self):
        """Return the current derived parts-case list, refreshing shared workflow state when available."""
        supplemented_cases: dict[str, object] = {}
        if self.workflow_state_service is not None:
            bluefolder_service = getattr(self.workflow_state_service, "bluefolder_service", None)
            if self.technician_directory_service is None:
                mappings = []
            else:
                operator_records = getattr(self.technician_directory_service, "operator_records", None)
                if callable(operator_records):
                    mappings = await operator_records(bluefolder_service=bluefolder_service)
                else:
                    mappings = self.technician_directory_service.mapping_records()
            await self.workflow_state_service.refresh_dispatch_attention(mappings)
            for case in self.workflow_state_service.current_snapshot().parts_cases:
                supplemented_cases[case.reference.strip().upper()] = case
        else:
            references = {record.reference for record in self.request_store.load()}
            for reference in sorted(references):
                case = await self._parts_case_for_reference(reference)
                supplemented_cases[case.reference.strip().upper()] = case

        tenant_active_cases = await self._tenant_active_parts_cases()
        for case in tenant_active_cases:
            supplemented_cases.setdefault(case.reference.strip().upper(), case)
        return list(supplemented_cases.values())

    async def _tenant_active_parts_cases(self) -> list[object]:
        """Return tenant-wide active-parts SR cases from BlueFolder status signals."""
        bluefolder_service = getattr(self.workflow_state_service, "bluefolder_service", None)
        if bluefolder_service is None:
            return []
        catalog = status_catalog_payload(base_path=self._bluefolder_base_path())
        active_statuses = [
            str(item.get("raw") or "").strip()
            for item in catalog.get("statusMeta", [])
            if isinstance(item, dict) and item.get("isActiveParts")
        ]
        if not active_statuses:
            return []

        service_requests = await bluefolder_service.get_service_requests_for_statuses(active_statuses)
        cases: list[object] = []
        seen_references: set[str] = set()
        for row in service_requests:
            sr_id = self._safe_int(row.get("id"))
            if sr_id is None:
                continue
            reference = f"SR-{sr_id}"
            if reference in seen_references:
                continue
            seen_references.add(reference)
            cases.append(await self._parts_case_for_reference(reference))
        return cases

    def _queue_summary_payload(self, summary: PartsRequestQueueSummary) -> dict[str, int]:
        """Serialize queue-summary counts for API responses."""
        return {
            "totalRequests": summary.total_requests,
            "openRequests": summary.open_requests,
            "assignedRequests": summary.assigned_requests,
            "unassignedRequests": summary.unassigned_requests,
            "syncedRequests": summary.synced_requests,
            "requestedCount": summary.requested_count,
            "orderedCount": summary.ordered_count,
            "receivedCount": summary.received_count,
            "resolvedCount": summary.resolved_count,
            "cancelledCount": summary.cancelled_count,
        }

    def _parts_case_metrics(self, cases) -> dict[str, object]:
        """Build aggregate metrics for the current parts-case list."""
        stage_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        age_counts: dict[str, int] = {}
        assigned_cases = 0
        for case in cases:
            stage_counts[case.stage] = stage_counts.get(case.stage, 0) + 1
            status_counts[case.status] = status_counts.get(case.status, 0) + 1
            if case.age_bucket is not None:
                age_counts[case.age_bucket] = age_counts.get(case.age_bucket, 0) + 1
            if case.assigned_parts_user_id is not None:
                assigned_cases += 1
        return {
            "stageCounts": stage_counts,
            "statusCounts": status_counts,
            "ageCounts": age_counts,
            "assignedCases": assigned_cases,
            "unassignedCases": max(len(cases) - assigned_cases, 0),
        }

    async def _parts_case_payload(self, case) -> dict[str, object]:
        """Serialize one derived parts case for API responses."""
        return {
            "caseId": case.case_id,
            "reference": case.reference,
            "srId": case.sr_id,
            "stage": case.stage,
            "stageLabel": case.stage_label,
            "status": case.status,
            "openRequestIds": case.open_request_ids,
            "assignedPartsUserId": case.assigned_parts_user_id,
            "assignedPartsLabel": (
                self._discord_user_label(case.assigned_parts_user_id)
                if case.assigned_parts_user_id is not None
                else None
            ),
            "requestedByUserId": case.requested_by_user_id,
            "requestedByLabel": (
                self._discord_user_label(case.requested_by_user_id)
                if case.requested_by_user_id is not None
                else None
            ),
            "technicianBluefolderUserId": case.technician_bluefolder_user_id,
            "technicianLabel": (
                self._technician_mapping_label_from_bluefolder(case.technician_bluefolder_user_id)
                if case.technician_bluefolder_user_id is not None
                else None
            ),
            "serviceRequestStatus": case.service_request_status,
            "serviceRequestStatusMeta": describe_service_request_status(
                case.service_request_status,
                base_path=self._bluefolder_base_path(),
            ),
            "latestStatusText": case.latest_status_text,
            "latestIssueText": case.latest_issue_text,
            "blocker": case.blocker,
            "nextAction": case.next_action,
            "updatedAt": case.updated_at,
            "ageHours": case.age_hours,
            "ageBucket": case.age_bucket,
        }

    async def _record_payload(self, record: PartRequestRecord) -> dict[str, object]:
        """Serialize one tracked parts request for API responses."""
        case = await self._parts_case_for_reference(record.reference)
        return {
            "requestId": record.request_id,
            "reference": record.reference,
            "description": record.description,
            "requestedByUserId": record.requested_by_user_id,
            "requestedByLabel": self._discord_user_label(record.requested_by_user_id),
            "technicianBluefolderUserId": record.technician_bluefolder_user_id,
            "technicianLabel": (
                self._technician_mapping_label(record) if record.technician_bluefolder_user_id is not None else None
            ),
            "assignedPartsUserId": record.assigned_parts_user_id,
            "assignedPartsLabel": (
                self._discord_user_label(record.assigned_parts_user_id)
                if record.assigned_parts_user_id is not None
                else None
            ),
            "status": record.status,
            "createdAt": record.created_at,
            "updatedAt": record.updated_at,
            "lastSyncedAt": record.last_synced_at,
            "lastReconciledAt": record.last_reconciled_at,
            "downstreamNote": record.downstream_note,
            "caseId": case.case_id,
            "caseStage": case.stage,
            "caseStageLabel": case.stage_label,
            "caseStatus": case.status,
            "nextAction": case.next_action,
            "blocker": case.blocker,
        }

    @staticmethod
    def _reference_sr_id(reference: str) -> int | None:
        candidate = reference.strip().upper()
        if not candidate.startswith("SR-"):
            return None
        value = candidate[3:]
        return int(value) if value.isdigit() else None

    @staticmethod
    def _safe_int(value: object) -> int | None:
        try:
            return int(str(value))
        except (TypeError, ValueError):
            return None

    def _bluefolder_base_path(self) -> str | None:
        """Return the configured BlueFolder library path when available through workflow services."""
        service = getattr(self.workflow_state_service, "bluefolder_service", None)
        adapter = getattr(service, "adapter", None)
        return getattr(adapter, "base_path", None)

    def _build_lookup_result(
        self,
        request: PartLookupRequest,
        summary: PartsWorkflowSummary,
        notification_mode: str,
        matching_records: list[PartRequestRecord],
    ) -> CommandResult:
        """Convert a typed parts summary into a user-facing command response."""
        lines = [
            f"**Part Lookup {summary.reference}**",
            "",
            *status_section("**Parts System**", status=summary.integration_status, details=summary.message),
        ]
        if summary.source_path is not None:
            lines.append(f"Handoff root: `{summary.source_path}`")
        if summary.export_path is not None:
            lines.append(
                f"Export file: `{summary.export_path}` ({'present' if summary.export_file_exists else 'missing'})"
            )
        if summary.receipt_path is not None:
            lines.append(
                f"Receipt file: `{summary.receipt_path}` ({'present' if summary.receipt_file_exists else 'missing'})"
            )

        lines.extend(["", *section("**Tracked Requests**")])
        if not matching_records:
            lines.append("No tracked parts requests found for this reference.")
        else:
            lines.append(f"Tracked requests: `{len(matching_records)}`")
            open_count = sum(1 for record in matching_records if record.status not in {"resolved", "cancelled"})
            lines.append(f"Open requests: `{open_count}`")
            for record in matching_records[:5]:
                lines.append(
                    f"`{record.request_id}` `{record.status}` requested by {self._discord_user_label(record.requested_by_user_id)}"
                )
                if record.assigned_parts_user_id is not None:
                    lines.append(f"Assigned to: {self._discord_user_label(record.assigned_parts_user_id)}")
                if record.last_synced_at is not None:
                    lines.append(f"Last synced: `{record.last_synced_at}`")
                if record.last_reconciled_at is not None:
                    lines.append(f"Last reconciled: `{record.last_reconciled_at}`")
                if record.downstream_note:
                    lines.append(f"Downstream note: {record.downstream_note}")
                lines.append(f"Description: {record.description}")
            if len(matching_records) > 5:
                lines.append(f"...and `{len(matching_records) - 5}` more tracked request(s)")

        context_lines = [
            *(
                [
                    "Requester: "
                    f"{self._technician_label(discord_user_id=request.requested_by_user_id, bluefolder_user_id=request.technician_bluefolder_user_id)}"
                ]
                if request.technician_bluefolder_user_id is not None
                else []
            ),
            *(
                [f"Requester: {self._discord_user_label(request.requested_by_user_id)} (admin)"]
                if request.requester_is_admin and request.technician_bluefolder_user_id is None
                else []
            ),
            f"Notifications: `{notification_mode}`",
        ]
        lines.extend(["", *section("**Context**", *context_lines)])
        return CommandResult(message="\n".join(lines))

    def _discord_user_label(self, user_id: int) -> str:
        """Render a Discord-facing user label."""
        if self.technician_directory_service is not None:
            return self.technician_directory_service.discord_mention(user_id)
        return f"<@{user_id}>"

    def _technician_label(self, *, discord_user_id: int | None = None, bluefolder_user_id: int | None = None) -> str:
        """Render the best available technician label."""
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

    def _technician_mapping_label(self, record: PartRequestRecord) -> str:
        """Render the technician mapping associated with a parts request."""
        return self._technician_label(
            discord_user_id=record.requested_by_user_id,
            bluefolder_user_id=record.technician_bluefolder_user_id,
        )

    def _technician_mapping_label_from_bluefolder(self, bluefolder_user_id: int) -> str:
        """Render a technician label from a BlueFolder user id."""
        return self._technician_label(bluefolder_user_id=bluefolder_user_id)


PartsCannonService = PartsHandoffService
