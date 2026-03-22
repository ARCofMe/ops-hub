"""Parts Cannon subsystem service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ops_hub.integrations.parts_cannon_adapter import PartsCannonAdapter
from ops_hub.models.requests import (
    CommandResult,
    PartLookupRequest,
    PartRequestCreate,
    PartRequestRecord,
    PartRequestUpdate,
    PartsWorkflowSummary,
)
from ops_hub.services.notifications import NotificationService
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
            operator_bluefolder_user_id=request.operator_bluefolder_user_id,
            status="requested",
            created_at=timestamp,
            updated_at=timestamp,
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
                    f"Parts request `{request_id}` created",
                    f"Reference: `{record.reference}`",
                    f"Status: `{record.status}`",
                    f"Description: {record.description}",
                ]
            )
        )

    async def list_requests(self, *, status: str | None = None) -> CommandResult:
        """List current parts requests, optionally filtered by status."""
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

        if not records:
            return CommandResult(message="No parts requests found.")

        lines = ["Parts requests"]
        for record in records[:15]:
            lines.append(
                f"`{record.request_id}` `{record.status}` `{record.reference}` {record.description}"
            )
        if len(records) > 15:
            lines.append(f"...and {len(records) - 15} more request(s)")
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
                operator_bluefolder_user_id=record.operator_bluefolder_user_id,
                status=normalized_status,
                created_at=record.created_at,
                updated_at=datetime.now(UTC).isoformat(timespec="seconds"),
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
                        f"Parts request `{updated.request_id}` updated",
                        f"Reference: `{updated.reference}`",
                        f"Status: `{updated.status}`",
                    ]
                )
            )

        return CommandResult(message=f"Parts request `{request.request_id}` was not found.")

    def supported_request_statuses(self) -> tuple[str, ...]:
        """Return the supported parts request statuses."""
        return PARTS_REQUEST_STATUSES

    def _normalize_status(self, status: str) -> str | None:
        """Normalize a requested parts status and reject unsupported values."""
        candidate = status.strip().lower()
        if candidate in PARTS_REQUEST_STATUSES:
            return candidate
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
                    f"Part `{summary.reference}`",
                    f"Parts Cannon: `{summary.integration_status}`",
                    f"Details: {summary.message}",
                    *([f"Requester mapping: BlueFolder user `{request.operator_bluefolder_user_id}`"] if request.operator_bluefolder_user_id is not None else []),
                    *(["Requester mapping: admin access"] if request.requester_is_admin and request.operator_bluefolder_user_id is None else []),
                    f"Notifications: `{notification_mode}`",
                ]
            )
        )
