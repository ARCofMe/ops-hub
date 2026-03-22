"""Placeholder adapter for photo ingest and compliance integration."""

from __future__ import annotations

from dataclasses import dataclass

from ops_hub.models.requests import PhotoIngestMessage, PhotoIngestResult

@dataclass(slots=True)
class PhotoIngestAdapter:
    """Adapter boundary for photo ingest behavior."""

    base_path: str | None = None

    async def healthcheck(self) -> dict[str, str]:
        """Return a placeholder photo-ingest health response.

        TODO: Plug in existing photo ingest and compliance projects here.
        """
        return {"status": "placeholder", "source": "photo_ingest_adapter"}

    async def ingest_message(self, message: PhotoIngestMessage) -> PhotoIngestResult:
        """Return a placeholder photo-ingest handling result.

        TODO: Wrap the existing photo ingest/compliance project instead of moving code here first.
        """
        if message.attachment_count <= 0:
            return PhotoIngestResult(
                handled=False,
                status="ignored_no_attachments",
                message="Message did not include attachments.",
            )

        return PhotoIngestResult(
            handled=True,
            status="placeholder_ready",
            message="Photo ingest listener received an attachment-bearing message.",
        )
