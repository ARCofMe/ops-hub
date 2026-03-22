"""Notification service boundary for Ops Hub alerts and notices."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import logging

from ops_hub.models.requests import NotificationRecord, NotificationStatus


logger = logging.getLogger(__name__)
NoticeSender = Callable[[int, str, str], Awaitable[None]]


@dataclass(slots=True)
class NotificationService:
    """Notification service with a dry-run delivery boundary.

    This keeps alerting logic centralized while real Discord/channel routing is still
    being phased into Ops Hub.
    """

    records: list[NotificationRecord] = field(default_factory=list)
    channel_id: int | None = None
    sender: NoticeSender | None = None

    def configure_sender(self, sender: NoticeSender) -> None:
        """Attach the runtime notice sender once the bot is ready."""
        self.sender = sender

    async def send_notice(self, *, topic: str, message: str) -> None:
        """Record and deliver a notice, using Discord routing when configured."""
        delivery = "dry_run"
        if self.channel_id is not None and self.sender is not None:
            try:
                await self.sender(self.channel_id, topic, message)
            except Exception:
                logger.exception(
                    "Failed to route notification to Discord channel",
                    extra={"channel_id": self.channel_id, "topic": topic},
                )
                delivery = "fallback_logger"
            else:
                delivery = "discord"

        record = NotificationRecord(topic=topic, message=message, delivery=delivery)
        self.records.append(record)
        logger.info("Notification placeholder", extra={"topic": topic, "message": message})

    async def status(self) -> NotificationStatus:
        """Return the current notification-service state."""
        last_topic = self.records[-1].topic if self.records else None
        if self.channel_id is not None and self.sender is not None:
            mode = "discord"
            transport = f"discord_channel:{self.channel_id}"
        elif self.channel_id is not None:
            mode = "discord_pending"
            transport = f"discord_channel:{self.channel_id}"
        else:
            mode = "dry_run"
            transport = "logger"
        return NotificationStatus(
            configured=True,
            mode=mode,
            transport=transport,
            notice_count=len(self.records),
            last_topic=last_topic,
        )

    async def recent_notices(self, limit: int = 5) -> list[NotificationRecord]:
        """Return the most recent notification attempts, newest first."""
        if limit <= 0:
            return []
        return list(reversed(self.records[-limit:]))
