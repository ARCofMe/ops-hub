"""Parts Cannon subsystem service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ops_hub.integrations.parts_cannon_adapter import PartsCannonAdapter
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
from ops_hub.services.parts_request_store import PartsRequestStore

PARTS_REQUEST_STATUSES: tuple[str, ...] = (
    "requested",
    "ordered",
    "received",
    "resolved",
    "cancelled",
)


@dataclass(slots=True)
class PartsCannonService:
    """Parts workflow service facade.

    Parts Cannon is an internal codename/subsystem inside Ops Hub, not the entire app.
    """

    adapter: PartsCannonAdapter
    notifications: NotificationService
    request_store: PartsRequestStore
    technician_directory_service: TechnicianDirectoryService | None = None

    async def lookup_part(self, request: PartLookupRequest) -> CommandResult:
        """Return a placeholder parts wrapper response."""
        # TODO: Wrap existing parts workflow logic here instead of moving code prematurely.
        result = await self.adapter.get_part_status(request.reference)
        await self.notifications.send_notice(
            topic="parts.lookup",
            message=f"Parts lookup requested for {request.reference} with status {result.integration_status}.",
        )
        notification_status = await self.notifications.status()
        return self._build_lookup_result(request, result, notification_status.mode)

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
        for record in records[:15]:
            lines.extend(
                [
                    "",
                    f"`{record.request_id}` `{record.status}` `{record.reference}`",
                    f"Requested by: {self._discord_user_label(record.requested_by_user_id)}",
                ]
            )
            if record.assigned_parts_user_id is not None:
                lines.append(f"Assigned to: {self._discord_user_label(record.assigned_parts_user_id)}")
            if record.last_synced_at is not None:
                lines.append(f"Last synced: `{record.last_synced_at}`")
            lines.append(f"Description: {record.description}")
        if len(records) > 15:
            lines.extend(["", f"...and {len(records) - 15} more request(s)"])
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

        lines = [
            f"**Parts Request {record.request_id}**",
            f"Reference: `{record.reference}`",
            f"Status: `{record.status}`",
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
            f"Status: `{export_result.integration_status}`",
            f"Details: {export_result.message}",
            f"Exported requests: `{export_result.exported_count}`",
        ]
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
            f"Status: `{import_result.integration_status}`",
            f"Details: {import_result.message}",
            f"Applied receipts: `{applied}`",
            f"Ignored receipts: `{ignored}`",
        ]
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

    def _build_lookup_result(
        self,
        request: PartLookupRequest,
        summary: PartsWorkflowSummary,
        notification_mode: str,
    ) -> CommandResult:
        """Convert a typed parts summary into a user-facing command response."""
        return CommandResult(
            message="\n".join(
                [
                    f"**Part Lookup {summary.reference}**",
                    "",
                    "**Parts System**",
                    f"Status: `{summary.integration_status}`",
                    f"Details: {summary.message}",
                    "",
                    "**Context**",
                    *(
                        [
                            "Requester: "
                            f"{self._technician_label(discord_user_id=request.requested_by_user_id, bluefolder_user_id=request.technician_bluefolder_user_id)}"
                        ]
                        if request.technician_bluefolder_user_id is not None
                        else []
                    ),
                    *([f"Requester: {self._discord_user_label(request.requested_by_user_id)} (admin)"] if request.requester_is_admin and request.technician_bluefolder_user_id is None else []),
                    f"Notifications: `{notification_mode}`",
                ]
            )
        )

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
