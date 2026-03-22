"""BlueFolder service facade."""

from __future__ import annotations

from dataclasses import dataclass

from ops_hub.integrations.bluefolder_adapter import BlueFolderAdapter


@dataclass(slots=True)
class BlueFolderService:
    """Service wrapper around BlueFolder-related operations."""

    adapter: BlueFolderAdapter

    async def get_job_summary(self, reference: str) -> dict[str, str]:
        """Delegate job-summary lookup to the adapter layer."""
        # TODO: Add read-only BlueFolder adapter integration first.
        return await self.adapter.get_job_summary(reference)

