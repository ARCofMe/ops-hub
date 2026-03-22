"""Request and response models used across services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class JobLookupRequest:
    """Input for job lookup operations."""

    reference: str
    requested_by_user_id: int


@dataclass(slots=True)
class PartLookupRequest:
    """Input for parts lookup operations."""

    reference: str
    requested_by_user_id: int


@dataclass(slots=True)
class CommandResult:
    """Simple user-facing command response."""

    message: str


@dataclass(slots=True)
class BlueFolderJobSummary:
    """Read-only job summary placeholder for future BlueFolder integration."""

    reference: str
    available: bool
    integration_status: str
    message: str
    source_path: Path | None = None
    service_request_id: str | None = None
    subject: str | None = None
    customer_id: str | None = None
    customer_location_id: str | None = None


@dataclass(slots=True)
class PhotoIngestMessage:
    """Minimal Discord message data passed into the photo-ingest service."""

    channel_id: int
    message_id: int
    author_id: int
    content: str
    attachment_count: int


@dataclass(slots=True)
class PhotoIngestResult:
    """Placeholder result for photo-ingest message handling."""

    handled: bool
    status: str
    message: str


@dataclass(slots=True)
class PartsWorkflowSummary:
    """Placeholder summary for a future parts workflow wrapper."""

    reference: str
    available: bool
    integration_status: str
    message: str
    source_path: Path | None = None
