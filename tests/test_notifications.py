"""Notification service tests for Ops Hub."""

from __future__ import annotations

import asyncio

from ops_hub.services.notifications import NotificationService


def test_notification_service_reports_empty_dry_run_status() -> None:
    service = NotificationService()

    status = asyncio.run(service.status())

    assert status.configured is True
    assert status.mode == "dry_run"
    assert status.transport == "logger"
    assert status.notice_count == 0
    assert status.last_topic is None


def test_notification_service_tracks_sent_notices() -> None:
    service = NotificationService()

    asyncio.run(service.send_notice(topic="parts.lookup", message="lookup happened"))
    status = asyncio.run(service.status())

    assert status.notice_count == 1
    assert status.last_topic == "parts.lookup"
    assert service.records[0].delivery == "dry_run"


def test_notification_service_routes_to_discord_sender_when_configured() -> None:
    sent: list[tuple[int, str, str]] = []

    async def _sender(channel_id: int, topic: str, message: str) -> None:
        sent.append((channel_id, topic, message))

    service = NotificationService(channel_id=123)
    service.configure_sender(_sender)

    asyncio.run(service.send_notice(topic="parts.lookup", message="lookup happened"))
    status = asyncio.run(service.status())

    assert sent == [(123, "parts.lookup", "lookup happened")]
    assert status.mode == "discord"
    assert status.transport == "discord_channel:123"
    assert service.records[0].delivery == "discord"


def test_notification_service_reports_pending_discord_mode_before_sender_attached() -> None:
    service = NotificationService(channel_id=123)

    status = asyncio.run(service.status())

    assert status.mode == "discord_pending"
    assert status.transport == "discord_channel:123"
