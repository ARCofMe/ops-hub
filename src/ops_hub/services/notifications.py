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
    channel_map: dict[str, int] = field(default_factory=dict)
    sender: NoticeSender | None = None

    def configure_sender(self, sender: NoticeSender) -> None:
        """Attach the runtime notice sender once the bot is ready."""
        self.sender = sender

    async def send_notice(self, *, topic: str, message: str) -> None:
        """Record and deliver a notice, using Discord routing when configured."""
        delivery = "dry_run"
        target_channel_id = self._resolve_channel_id(topic)
        if target_channel_id is not None and self.sender is not None:
            try:
                await self.sender(target_channel_id, topic, message)
            except Exception:
                logger.exception(
                    "Failed to route notification to Discord channel",
                    extra={"channel_id": target_channel_id, "topic": topic},
                )
                delivery = "fallback_logger"
            else:
                delivery = f"discord:{target_channel_id}"

        record = NotificationRecord(topic=topic, message=message, delivery=delivery)
        self.records.append(record)
        logger.info("Notification placeholder", extra={"topic": topic, "notice_message": message})

    async def status(self) -> NotificationStatus:
        """Return the current notification-service state."""
        last_topic = self.records[-1].topic if self.records else None
        if self.channel_map:
            route_count = len(self.channel_map)
            if self.sender is not None:
                mode = "discord_routed"
            else:
                mode = "discord_routes_pending"
            transport = f"discord_routes:{route_count}"
        elif self.channel_id is not None and self.sender is not None:
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

    def _resolve_channel_id(self, topic: str) -> int | None:
        """Resolve the best notification channel for a topic."""
        best_match = None
        best_channel_id = None
        for prefix, channel_id in self.channel_map.items():
            normalized_prefix = prefix.strip()
            if not normalized_prefix:
                continue
            if topic == normalized_prefix or topic.startswith(f"{normalized_prefix}."):
                if best_match is None or len(normalized_prefix) > len(best_match):
                    best_match = normalized_prefix
                    best_channel_id = channel_id
        if best_channel_id is not None:
            return best_channel_id
        return self.channel_id
