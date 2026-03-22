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
