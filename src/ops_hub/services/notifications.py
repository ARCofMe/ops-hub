"""Notification service boundary for Ops Hub alerts and notices."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging

from ops_hub.models.requests import NotificationRecord, NotificationStatus


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class NotificationService:
    """Notification service with a dry-run delivery boundary.

    This keeps alerting logic centralized while real Discord/channel routing is still
    being phased into Ops Hub.
    """

    records: list[NotificationRecord] = field(default_factory=list)

    async def send_notice(self, *, topic: str, message: str) -> None:
        """Record and log a dry-run notification until real routing is added."""
        # TODO: Add Discord channel routing, alert fan-out, and notification policies later.
        record = NotificationRecord(topic=topic, message=message, delivery="dry_run")
        self.records.append(record)
        logger.info("Notification placeholder", extra={"topic": topic, "message": message})

    async def status(self) -> NotificationStatus:
        """Return the current notification-service state."""
        last_topic = self.records[-1].topic if self.records else None
        return NotificationStatus(
            configured=True,
            mode="dry_run",
            transport="logger",
            notice_count=len(self.records),
            last_topic=last_topic,
        )
