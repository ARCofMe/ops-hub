"""Technician API dispatch tests."""

from __future__ import annotations

import asyncio
from http import HTTPStatus
from types import SimpleNamespace

from ops_hub.api_server import dispatch_technician_api_request


async def _health() -> dict[str, bool]:
    return {"ok": True}


async def _today_jobs(**_: object) -> list[dict[str, str]]:
    return [{"id": "100", "customerName": "Pat"}]


def test_dispatch_requires_authorization() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(technician_api_service=SimpleNamespace(health=_health))

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="GET",
            path="/health",
            headers={},
        )
    )

    assert status == HTTPStatus.UNAUTHORIZED
    assert payload == {"success": False, "message": "Unauthorized"}


def test_dispatch_returns_today_jobs() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        technician_api_service=SimpleNamespace(
            health=_health,
            resolve_technician=lambda **_: (123, 9001),
            get_today=_today_jobs,
        )
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="GET",
            path="/tech/me/today",
            headers={"Authorization": "Bearer secret", "X-Technician-Subject": "123"},
        )
    )

    assert status == HTTPStatus.OK
    assert payload == [{"id": "100", "customerName": "Pat"}]


def test_dispatch_returns_job_parts_case() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        technician_api_service=SimpleNamespace(
            health=_health,
            resolve_technician=lambda **_: (123, 9001),
            get_job_parts_case=lambda **_: asyncio.sleep(0, result={"stageLabel": "Ready for Scheduling"}),
        )
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="GET",
            path="/tech/jobs/100/parts",
            headers={"Authorization": "Bearer secret", "X-Technician-Subject": "123"},
        )
    )

    assert status == HTTPStatus.OK
    assert payload == {"stageLabel": "Ready for Scheduling"}


def test_dispatch_returns_job_timeline() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        technician_api_service=SimpleNamespace(
            health=_health,
            resolve_technician=lambda **_: (123, 9001),
            get_job_timeline=lambda **_: asyncio.sleep(0, result=[{"summary": "Technician started work."}]),
        )
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="GET",
            path="/tech/jobs/100/timeline",
            headers={"Authorization": "Bearer secret", "X-Technician-Subject": "123"},
        )
    )

    assert status == HTTPStatus.OK
    assert payload == [{"summary": "Technician started work."}]
