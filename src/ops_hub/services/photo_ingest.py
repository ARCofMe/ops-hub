"""Photo ingest service facade."""

from __future__ import annotations

from dataclasses import dataclass

from ops_hub.core.config import Settings
from ops_hub.integrations.photo_ingest_adapter import PhotoIngestAdapter
from ops_hub.models.requests import PhotoIngestMessage, PhotoIngestResult


@dataclass(slots=True)
class PhotoIngestService:
    """Photo ingest and compliance service facade."""

    settings: Settings
    adapter: PhotoIngestAdapter

    async def status(self) -> dict[str, str]:
        """Return placeholder photo-ingest status."""
        # TODO: Add a Discord channel listener that wraps the current photo ingest flow.
        return await self.adapter.healthcheck()

    def should_process_channel(self, channel_id: int) -> bool:
        """Return whether the message channel should be handled by the listener."""
        configured_channel_id = self.settings.photo_ingest_channel_id
        return configured_channel_id is not None and channel_id == configured_channel_id

    async def handle_message(self, message: PhotoIngestMessage) -> PhotoIngestResult:
        """Handle a message routed from the Discord listener layer."""
        # TODO: Add message-to-ingest translation and compliance workflow wiring.
        if not self.should_process_channel(message.channel_id):
            return PhotoIngestResult(
                handled=False,
                status="ignored_channel",
                message="Message is not in the configured photo ingest channel.",
            )
        return await self.adapter.ingest_message(message)
