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
