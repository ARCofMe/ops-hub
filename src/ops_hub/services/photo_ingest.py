"""Photo ingest service facade."""

from __future__ import annotations

from dataclasses import dataclass

from ops_hub.core.config import Settings
from ops_hub.integrations.photo_ingest_adapter import PhotoIngestAdapter
from ops_hub.models.requests import (
    CommandResult,
    PhotoAttachmentPayload,
    PhotoIngestMessage,
    PhotoIngestResult,
)


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

    async def attach_model_serial_photo(
        self,
        sr_id: int,
        *,
        photo: PhotoAttachmentPayload,
        requested_by_user_id: int,
    ) -> CommandResult:
        """Attach a compressed model/serial photo to a BlueFolder service request."""
        result = await self.adapter.attach_photo_to_service_request(
            sr_id,
            photo=photo,
            uploaded_by_user_id=requested_by_user_id,
            label="MDLSN",
        )
        return CommandResult(message=result.message)

    async def archive_job_photos(
        self,
        sr_id: int,
        *,
        photos: list[PhotoAttachmentPayload],
        requested_by_user_id: int,
        sr_subject: str | None = None,
    ) -> CommandResult:
        """Send a batch of compressed job photos to the configured archive mailbox."""
        result = await self.adapter.archive_photos_via_email(
            sr_id,
            photos=photos,
            uploaded_by_user_id=requested_by_user_id,
            sr_subject=sr_subject,
        )
        return CommandResult(message=result.message)
