"""Parts Cannon subsystem service."""

from __future__ import annotations

from dataclasses import dataclass

from ops_hub.integrations.parts_cannon_adapter import PartsCannonAdapter
from ops_hub.models.requests import CommandResult, PartLookupRequest, PartsWorkflowSummary
from ops_hub.services.notifications import NotificationService


@dataclass(slots=True)
class PartsCannonService:
    """Parts workflow service facade.

    Parts Cannon is an internal codename/subsystem inside Ops Hub, not the entire app.
    """

    adapter: PartsCannonAdapter
    notifications: NotificationService

    async def lookup_part(self, request: PartLookupRequest) -> CommandResult:
        """Return a placeholder parts wrapper response."""
        # TODO: Wrap existing parts workflow logic here instead of moving code prematurely.
        result = await self.adapter.get_part_status(request.reference)
        await self.notifications.send_notice(
            topic="parts.lookup",
            message=f"Parts lookup requested for {request.reference} with status {result.integration_status}.",
        )
        notification_status = await self.notifications.status()
        return self._build_lookup_result(result, notification_status.mode)

    def _build_lookup_result(self, summary: PartsWorkflowSummary, notification_mode: str) -> CommandResult:
        """Convert a typed parts summary into a user-facing command response."""
        return CommandResult(
            message="\n".join(
                [
                    f"Part `{summary.reference}`",
                    f"Parts Cannon: `{summary.integration_status}`",
                    f"Details: {summary.message}",
                    f"Notifications: `{notification_mode}`",
                ]
            )
        )
