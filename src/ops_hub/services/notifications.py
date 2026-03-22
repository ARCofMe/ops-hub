"""Notification service placeholder."""

from __future__ import annotations

from dataclasses import dataclass
import logging


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class NotificationService:
    """Placeholder notification service for future alerts and routing hooks."""

    async def send_notice(self, *, topic: str, message: str) -> None:
        """Log notification requests until real routing is added."""
        # TODO: Add Discord channel routing, alert fan-out, and notification policies later.
        logger.info("Notification placeholder", extra={"topic": topic, "message": message})

