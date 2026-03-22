"""Parts Cannon subsystem service."""

from __future__ import annotations

from dataclasses import dataclass

from ops_hub.integrations.parts_cannon_adapter import PartsCannonAdapter
from ops_hub.models.requests import CommandResult, PartLookupRequest
from ops_hub.services.notifications import NotificationService


@dataclass(slots=True)
class PartsCannonService:
    """Parts workflow service facade.

    Parts Cannon is an internal codename/subsystem inside Ops Hub, not the entire app.
    """

    adapter: PartsCannonAdapter
    notifications: NotificationService

    async def lookup_part(self, request: PartLookupRequest) -> CommandResult:
        """Return a placeholder parts response."""
        # TODO: Wrap existing parts workflow logic here instead of moving code prematurely.
        result = await self.adapter.get_part_status(request.reference)
        return CommandResult(
            message=(
                f"Parts Cannon placeholder for `{request.reference}`. "
                f"Current source: {result['source']}."
            )
        )

