"""Photo ingest service facade."""

from __future__ import annotations

from dataclasses import dataclass

from ops_hub.integrations.photo_ingest_adapter import PhotoIngestAdapter


@dataclass(slots=True)
class PhotoIngestService:
    """Photo ingest and compliance service facade."""

    adapter: PhotoIngestAdapter

    async def status(self) -> dict[str, str]:
        """Return placeholder photo-ingest status."""
        # TODO: Add a Discord channel listener that wraps the current photo ingest flow.
        return await self.adapter.healthcheck()

