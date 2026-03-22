"""Request and response models used across services."""

from __future__ import annotations

from dataclasses import dataclass


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

