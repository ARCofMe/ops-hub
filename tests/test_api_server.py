"""Technician API dispatch tests."""

from __future__ import annotations

import asyncio
from http import HTTPStatus
from types import SimpleNamespace

from ops_hub.api_server import dispatch_technician_api_request, render_landing_page


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


def test_landing_page_promotes_ops_hub_workspaces() -> None:
    html = render_landing_page()

    assert "<title>OpsHub | Service Operations Command Center</title>" in html
    assert "Service operations brain" in html
    assert "https://routedesk.ops-hub.org" in html
    assert "https://partsdesk.ops-hub.org" in html
    assert "technician API token" in html


def test_dispatch_returns_ecosystem_status() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(technician_api_service=SimpleNamespace(health=_health))

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="GET",
            path="/ecosystem/status",
            headers={"Authorization": "Bearer secret"},
        )
    )

    assert status == HTTPStatus.OK
    assert payload["success"] is True
    assert payload["role"] == "brain"
    assert [item["name"] for item in payload["frontends"]] == ["RouteDesk", "PartsDesk", "FieldDesk"]


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


def test_dispatch_returns_intake_formats() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        dispatch_service=SimpleNamespace(),
        technician_api_service=SimpleNamespace(health=_health),
        technician_directory_service=SimpleNamespace(
            resolve_identity=lambda **_: SimpleNamespace(discord_user_id=123, is_dispatcher=True, is_admin=False)
        ),
        service_smith_service=SimpleNamespace(
            list_formats_payload=lambda: {"items": [{"name": "default"}]}
        ),
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="GET",
            path="/dispatch/intake/formats",
            headers={"Authorization": "Bearer secret", "X-Dispatch-Subject": "123"},
        )
    )

    assert status == HTTPStatus.OK
    assert payload == {"items": [{"name": "default"}]}


def test_dispatch_accepts_local_operator_id() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        dispatch_service=SimpleNamespace(get_dispatch_board_payload=lambda: asyncio.sleep(0, result={"ok": True})),
        technician_api_service=SimpleNamespace(health=_health),
        technician_directory_service=SimpleNamespace(
            resolve_operator_identity=lambda **_: SimpleNamespace(
                operator_id="route-desk",
                actor_user_id=2001,
                discord_user_id=None,
                is_dispatcher=True,
                is_admin=False,
            )
        ),
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="GET",
            path="/dispatch/board",
            headers={"Authorization": "Bearer secret", "X-Dispatch-Subject": "route-desk"},
        )
    )

    assert status == HTTPStatus.OK
    assert payload == {"ok": True}


def test_dispatch_returns_intake_profiles() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        dispatch_service=SimpleNamespace(),
        technician_api_service=SimpleNamespace(health=_health),
        technician_directory_service=SimpleNamespace(
            resolve_identity=lambda **_: SimpleNamespace(discord_user_id=123, is_dispatcher=True, is_admin=False)
        ),
        service_smith_service=SimpleNamespace(
            list_profiles_payload=lambda: {"items": [{"name": "vendor-a"}]}
        ),
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="GET",
            path="/dispatch/intake/profiles",
            headers={"Authorization": "Bearer secret", "X-Dispatch-Subject": "123"},
        )
    )

    assert status == HTTPStatus.OK
    assert payload == {"items": [{"name": "vendor-a"}]}


def test_dispatch_saves_intake_profile() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        dispatch_service=SimpleNamespace(),
        technician_api_service=SimpleNamespace(health=_health),
        technician_directory_service=SimpleNamespace(
            resolve_identity=lambda **_: SimpleNamespace(discord_user_id=123, is_dispatcher=True, is_admin=False)
        ),
        service_smith_service=SimpleNamespace(
            save_profile_payload=lambda **kwargs: {"profile": {"name": kwargs["name"]}, "success": True}
        ),
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="POST",
            path="/dispatch/intake/profiles",
            headers={"Authorization": "Bearer secret", "X-Dispatch-Subject": "123"},
            body={"name": "vendor-a", "formatName": "default"},
        )
    )

    assert status == HTTPStatus.OK
    assert payload == {"profile": {"name": "vendor-a"}, "success": True}


def test_dispatch_runs_bulk_attention_action() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        dispatch_service=SimpleNamespace(
            apply_bulk_dispatch_attention_action=lambda **kwargs: asyncio.sleep(
                0,
                result={
                    "success": True,
                    "action": kwargs["action"],
                    "requestedCount": len(kwargs["item_ids"]),
                },
            )
        ),
        technician_api_service=SimpleNamespace(health=_health),
        technician_directory_service=SimpleNamespace(
            resolve_identity=lambda **_: SimpleNamespace(discord_user_id=123, is_dispatcher=True, is_admin=False)
        ),
        service_smith_service=SimpleNamespace(),
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="POST",
            path="/dispatch/attention/bulk",
            headers={"Authorization": "Bearer secret", "X-Dispatch-Subject": "123"},
            body={"action": "ack", "itemIds": ["dispatch:SR-1:quote_needed", "dispatch:SR-2:part_ready"]},
        )
    )

    assert status == HTTPStatus.OK
    assert payload == {"success": True, "action": "ack", "requestedCount": 2}


def test_dispatch_analyzes_intake_spreadsheet() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        dispatch_service=SimpleNamespace(),
        technician_api_service=SimpleNamespace(health=_health),
        technician_directory_service=SimpleNamespace(
            resolve_identity=lambda **_: SimpleNamespace(discord_user_id=123, is_dispatcher=True, is_admin=False)
        ),
        service_smith_service=SimpleNamespace(
            analyze_spreadsheet_payload=lambda **kwargs: {"spreadsheetPath": kwargs["spreadsheet_path"], "rowCount": 2}
        ),
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="POST",
            path="/dispatch/intake/analyze",
            headers={"Authorization": "Bearer secret", "X-Dispatch-Subject": "123"},
            body={"spreadsheetPath": "/tmp/jobs.csv", "format": "default"},
        )
    )

    assert status == HTTPStatus.OK
    assert payload == {"spreadsheetPath": "/tmp/jobs.csv", "rowCount": 2}


def test_dispatch_previews_intake_import() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        dispatch_service=SimpleNamespace(),
        technician_api_service=SimpleNamespace(health=_health),
        technician_directory_service=SimpleNamespace(
            resolve_identity=lambda **_: SimpleNamespace(discord_user_id=123, is_dispatcher=True, is_admin=False)
        ),
        service_smith_service=SimpleNamespace(
            preview_import_payload=lambda **kwargs: {"previewMode": kwargs["preview_mode"], "rowCount": 1}
        ),
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="POST",
            path="/dispatch/intake/preview",
            headers={"Authorization": "Bearer secret", "X-Dispatch-Subject": "123"},
            body={"spreadsheetPath": "/tmp/jobs.csv", "previewMode": "payload_preview"},
        )
    )

    assert status == HTTPStatus.OK
    assert payload == {"previewMode": "payload_preview", "rowCount": 1}


def test_dispatch_imports_intake_spreadsheet() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        dispatch_service=SimpleNamespace(),
        technician_api_service=SimpleNamespace(health=_health),
        technician_directory_service=SimpleNamespace(
            resolve_identity=lambda **_: SimpleNamespace(discord_user_id=123, is_dispatcher=True, is_admin=False)
        ),
        service_smith_service=SimpleNamespace(
            import_spreadsheet_payload=lambda **kwargs: {"rowCount": 1, "summary": {"status:imported": 1}}
        ),
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="POST",
            path="/dispatch/intake/import",
            headers={"Authorization": "Bearer secret", "X-Dispatch-Subject": "123"},
            body={"spreadsheetPath": "/tmp/jobs.csv"},
        )
    )

    assert status == HTTPStatus.OK
    assert payload == {"rowCount": 1, "summary": {"status:imported": 1}}


def test_dispatch_previews_manual_service_request() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        dispatch_service=SimpleNamespace(),
        technician_api_service=SimpleNamespace(health=_health),
        technician_directory_service=SimpleNamespace(
            resolve_identity=lambda **_: SimpleNamespace(discord_user_id=123, is_dispatcher=True, is_admin=False)
        ),
        service_smith_service=SimpleNamespace(
            preview_manual_service_request_payload=lambda **kwargs: {
                "mode": "manual_service_request",
                "duplicateMode": kwargs["duplicate_mode"],
                "row": kwargs["request"],
            }
        ),
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="POST",
            path="/dispatch/intake/manual/preview",
            headers={"Authorization": "Bearer secret", "X-Dispatch-Subject": "123"},
            body={"request": {"customerName": "Pat Smith", "subject": "No heat"}, "duplicateMode": "error"},
        )
    )

    assert status == HTTPStatus.OK
    assert payload == {
        "mode": "manual_service_request",
        "duplicateMode": "error",
        "row": {"customerName": "Pat Smith", "subject": "No heat"},
    }


def test_dispatch_imports_manual_service_request() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        dispatch_service=SimpleNamespace(),
        technician_api_service=SimpleNamespace(health=_health),
        technician_directory_service=SimpleNamespace(
            resolve_identity=lambda **_: SimpleNamespace(discord_user_id=123, is_dispatcher=True, is_admin=False)
        ),
        service_smith_service=SimpleNamespace(
            import_manual_service_request_payload=lambda **kwargs: {
                "mode": "manual_service_request",
                "duplicateMode": kwargs["duplicate_mode"],
                "confirmed": kwargs["confirmed"],
                "allowValidationOverride": kwargs["allow_validation_override"],
            }
        ),
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="POST",
            path="/dispatch/intake/manual/import",
            headers={"Authorization": "Bearer secret", "X-Dispatch-Subject": "123"},
            body={
                "request": {"customerName": "Pat Smith", "subject": "No heat"},
                "duplicateMode": "error",
                "confirmed": True,
                "allowValidationOverride": True,
            },
        )
    )

    assert status == HTTPStatus.OK
    assert payload == {
        "mode": "manual_service_request",
        "duplicateMode": "error",
        "confirmed": True,
        "allowValidationOverride": True,
    }


def test_dispatch_rejects_non_object_manual_service_request_payload() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        dispatch_service=SimpleNamespace(),
        technician_api_service=SimpleNamespace(health=_health),
        technician_directory_service=SimpleNamespace(
            resolve_identity=lambda **_: SimpleNamespace(discord_user_id=123, is_dispatcher=True, is_admin=False)
        ),
        service_smith_service=SimpleNamespace(),
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="POST",
            path="/dispatch/intake/manual/preview",
            headers={"Authorization": "Bearer secret", "X-Dispatch-Subject": "123"},
            body=["not", "an", "object"],
        )
    )

    assert status == HTTPStatus.BAD_REQUEST
    assert payload == {"success": False, "message": "Manual intake payload must be a JSON object."}


def test_dispatch_returns_sr_work_payload() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        dispatch_service=SimpleNamespace(
            get_dispatch_sr_work_payload=lambda **kwargs: asyncio.sleep(0, result={"srId": kwargs["sr_id"], "urgentCount": 1})
        ),
        technician_api_service=SimpleNamespace(health=_health),
        technician_directory_service=SimpleNamespace(
            resolve_identity=lambda **_: SimpleNamespace(discord_user_id=123, is_dispatcher=True, is_admin=False)
        ),
        service_smith_service=SimpleNamespace(),
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="GET",
            path="/dispatch/sr/200/work",
            headers={"Authorization": "Bearer secret", "X-Dispatch-Subject": "123"},
        )
    )

    assert status == HTTPStatus.OK
    assert payload == {"srId": 200, "urgentCount": 1}


def test_dispatch_returns_sr_photo_compliance_payload() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        dispatch_service=SimpleNamespace(
            get_dispatch_sr_photo_compliance_payload=lambda **kwargs: asyncio.sleep(
                0,
                result={"srId": kwargs["sr_id"], "mailboxStatus": "found", "shouldNotify": False},
            )
        ),
        technician_api_service=SimpleNamespace(health=_health),
        technician_directory_service=SimpleNamespace(
            resolve_identity=lambda **_: SimpleNamespace(discord_user_id=123, is_dispatcher=True, is_admin=False)
        ),
        service_smith_service=SimpleNamespace(),
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="GET",
            path="/dispatch/sr/200/photo_compliance",
            headers={"Authorization": "Bearer secret", "X-Dispatch-Subject": "123"},
        )
    )

    assert status == HTTPStatus.OK
    assert payload == {"srId": 200, "mailboxStatus": "found", "shouldNotify": False}


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


def test_dispatch_returns_job_photo_status() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        technician_api_service=SimpleNamespace(
            health=_health,
            resolve_technician=lambda **_: (123, 9001),
            get_job_photo_status=lambda **_: asyncio.sleep(0, result={"mailboxStatus": "present"}),
        )
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="GET",
            path="/tech/jobs/100/photos",
            headers={"Authorization": "Bearer secret", "X-Technician-Subject": "123"},
        )
    )

    assert status == HTTPStatus.OK
    assert payload == {"mailboxStatus": "present"}


def test_dispatch_uploads_job_photo() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        technician_api_service=SimpleNamespace(
            health=_health,
            resolve_technician=lambda **_: (123, 9001),
            upload_job_photo=lambda **kwargs: asyncio.sleep(0, result=kwargs),
        )
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="POST",
            path="/tech/jobs/100/photos/upload",
            headers={"Authorization": "Bearer secret", "X-Technician-Subject": "123"},
            body={"label": "Model", "filename": "model.jpg", "contentType": "image/jpeg", "dataBase64": "aGVsbG8="},
        )
    )

    assert status == HTTPStatus.OK
    assert payload["sr_id"] == 100
    assert payload["filename"] == "model.jpg"


def test_dispatch_posts_quote_needed() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        technician_api_service=SimpleNamespace(
            health=_health,
            resolve_technician=lambda **_: (123, 9001),
            report_quote_needed=lambda **kwargs: asyncio.sleep(0, result=kwargs),
        )
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="POST",
            path="/tech/jobs/100/quote_needed",
            headers={"Authorization": "Bearer secret", "X-Technician-Subject": "123"},
            body={"details": "Need landlord approval", "subtype": "landlord"},
        )
    )

    assert status == HTTPStatus.OK
    assert payload["sr_id"] == 100
    assert payload["details"] == "Need landlord approval"
    assert payload["subtype"] == "landlord"


def test_dispatch_posts_no_answer() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        technician_api_service=SimpleNamespace(
            health=_health,
            resolve_technician=lambda **_: (123, 9001),
            report_no_answer=lambda **kwargs: asyncio.sleep(0, result=kwargs),
        )
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="POST",
            path="/tech/jobs/100/no_answer",
            headers={"Authorization": "Bearer secret", "X-Technician-Subject": "123"},
            body={"details": "Called twice with no response."},
        )
    )

    assert status == HTTPStatus.OK
    assert payload["sr_id"] == 100
    assert payload["details"] == "Called twice with no response."


def test_dispatch_posts_start() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        technician_api_service=SimpleNamespace(
            health=_health,
            resolve_technician=lambda **_: (123, 9001),
            log_work_start=lambda **kwargs: asyncio.sleep(0, result=kwargs),
        )
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="POST",
            path="/tech/jobs/100/start",
            headers={"Authorization": "Bearer secret", "X-Technician-Subject": "123"},
            body={"details": "Started diagnostic with unit energized."},
        )
    )

    assert status == HTTPStatus.OK
    assert payload["sr_id"] == 100
    assert payload["details"] == "Started diagnostic with unit energized."


def test_dispatch_posts_not_home() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        technician_api_service=SimpleNamespace(
            health=_health,
            resolve_technician=lambda **_: (123, 9001),
            report_not_home=lambda **kwargs: asyncio.sleep(0, result=kwargs),
        )
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="POST",
            path="/tech/jobs/100/not_home",
            headers={"Authorization": "Bearer secret", "X-Technician-Subject": "123"},
            body={"details": "House vacant on arrival."},
        )
    )

    assert status == HTTPStatus.OK
    assert payload["sr_id"] == 100
    assert payload["details"] == "House vacant on arrival."


def test_dispatch_posts_unable_to_complete() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        technician_api_service=SimpleNamespace(
            health=_health,
            resolve_technician=lambda **_: (123, 9001),
            report_unable_to_complete=lambda **kwargs: asyncio.sleep(0, result=kwargs),
        )
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="POST",
            path="/tech/jobs/100/unable_to_complete",
            headers={"Authorization": "Bearer secret", "X-Technician-Subject": "123"},
            body={"reason": "Vendor portal outage blocked warranty closeout."},
        )
    )

    assert status == HTTPStatus.OK
    assert payload["sr_id"] == 100
    assert payload["reason"] == "Vendor portal outage blocked warranty closeout."


def test_dispatch_returns_dispatch_board() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        technician_api_service=SimpleNamespace(health=_health),
        technician_directory_service=SimpleNamespace(
            resolve_identity=lambda **_: SimpleNamespace(discord_user_id=99, is_dispatcher=True, is_admin=False)
        ),
        dispatch_service=SimpleNamespace(
            get_dispatch_board_payload=lambda: asyncio.sleep(0, result={"mappedTechs": 2, "attentionJobs": 3})
        ),
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="GET",
            path="/dispatch/board",
            headers={"Authorization": "Bearer secret", "X-Dispatch-Subject": "99"},
        )
    )

    assert status == HTTPStatus.OK
    assert payload == {"mappedTechs": 2, "attentionJobs": 3}


def test_dispatch_posts_triage_disposition() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        technician_api_service=SimpleNamespace(health=_health),
        technician_directory_service=SimpleNamespace(
            resolve_identity=lambda **_: SimpleNamespace(discord_user_id=99, is_dispatcher=True, is_admin=False)
        ),
        dispatch_service=SimpleNamespace(
            set_dispatch_triage_disposition=lambda **kwargs: asyncio.sleep(0, result=SimpleNamespace(message="Triage updated"))
        ),
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="POST",
            path="/dispatch/triage/100/disposition",
            headers={"Authorization": "Bearer secret", "X-Dispatch-Subject": "99"},
            body={"disposition": "parts_first", "details": "Likely control board"},
        )
    )

    assert status == HTTPStatus.OK
    assert payload == {"success": True, "message": "Triage updated", "srId": 100, "disposition": "parts_first"}


def test_dispatch_returns_route_preview_payload() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    captured: dict[str, object] = {}

    async def _route_payload(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"technicianBluefolderUserId": 9001, "mappableStops": 3, "routeUrl": "https://example.test/route"}

    container = SimpleNamespace(
        technician_api_service=SimpleNamespace(health=_health),
        technician_directory_service=SimpleNamespace(
            resolve_identity=lambda **_: SimpleNamespace(discord_user_id=99, is_dispatcher=True, is_admin=False)
        ),
        dispatch_service=SimpleNamespace(
            get_dispatch_route_payload=_route_payload
        ),
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="GET",
            path="/dispatch/routes/preview?bluefolder_user_id=9001&optimize=true",
            headers={"Authorization": "Bearer secret", "X-Dispatch-Subject": "99"},
        )
    )

    assert status == HTTPStatus.OK
    assert payload["technicianBluefolderUserId"] == 9001
    assert payload["mappableStops"] == 3
    assert captured["optimize"] is True


def test_dispatch_returns_bad_request_when_route_preview_validation_fails() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        technician_api_service=SimpleNamespace(health=_health),
        technician_directory_service=SimpleNamespace(
            resolve_identity=lambda **_: SimpleNamespace(discord_user_id=99, is_dispatcher=True, is_admin=False)
        ),
        dispatch_service=SimpleNamespace(
            get_dispatch_route_payload=lambda **_: asyncio.sleep(0, result=(_ for _ in ()).throw(ValueError("Route date is invalid")))
        ),
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="GET",
            path="/dispatch/routes/preview?bluefolder_user_id=9001",
            headers={"Authorization": "Bearer secret", "X-Dispatch-Subject": "99"},
        )
    )

    assert status == HTTPStatus.BAD_REQUEST
    assert payload == {"success": False, "message": "Route date is invalid"}


def test_dispatch_returns_heatmap_payload() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        technician_api_service=SimpleNamespace(health=_health),
        technician_directory_service=SimpleNamespace(
            resolve_identity=lambda **_: SimpleNamespace(discord_user_id=99, is_dispatcher=True, is_admin=False)
        ),
        dispatch_service=SimpleNamespace(
            get_dispatch_heatmap_payload=lambda **_: asyncio.sleep(
                0,
                result={"scannedJobs": 6, "uniqueMappedLocations": 4, "hotspots": []},
            )
        ),
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="GET",
            path="/dispatch/routes/heatmap",
            headers={"Authorization": "Bearer secret", "X-Dispatch-Subject": "99"},
        )
    )

    assert status == HTTPStatus.OK
    assert payload["scannedJobs"] == 6
    assert payload["uniqueMappedLocations"] == 4


def test_dispatch_posts_attention_ack() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        technician_api_service=SimpleNamespace(health=_health),
        technician_directory_service=SimpleNamespace(
            resolve_identity=lambda **_: SimpleNamespace(discord_user_id=99, is_dispatcher=True, is_admin=False)
        ),
        dispatch_service=SimpleNamespace(
            acknowledge_dispatch_attention_item=lambda **kwargs: asyncio.sleep(0, result=kwargs)
        ),
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="POST",
            path="/dispatch/attention/dispatch:SR-100:quote_needed:landlord/ack",
            headers={"Authorization": "Bearer secret", "X-Dispatch-Subject": "99"},
            body={},
        )
    )

    assert status == HTTPStatus.OK
    assert payload["item_id"] == "dispatch:SR-100:quote_needed:landlord"
    assert payload["actor_user_id"] == 99


def test_dispatch_posts_attention_assign_with_bluefolder_owner() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        technician_api_service=SimpleNamespace(health=_health),
        technician_directory_service=SimpleNamespace(
            resolve_identity=lambda **_: SimpleNamespace(discord_user_id=99, is_dispatcher=True, is_admin=False)
        ),
        dispatch_service=SimpleNamespace(
            assign_dispatch_attention_item=lambda **kwargs: asyncio.sleep(0, result=kwargs)
        ),
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="POST",
            path="/dispatch/attention/dispatch:SR-100:quote_needed/assign",
            headers={"Authorization": "Bearer secret", "X-Dispatch-Subject": "99"},
            body={"assignedOwnerBluefolderUserId": 1001},
        )
    )

    assert status == HTTPStatus.OK
    assert payload["item_id"] == "dispatch:SR-100:quote_needed"
    assert payload["assigned_owner_bluefolder_user_id"] == 1001
    assert payload["actor_user_id"] == 99


def test_dispatch_gets_attention_item_with_encoded_item_id() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        technician_api_service=SimpleNamespace(health=_health),
        technician_directory_service=SimpleNamespace(
            resolve_identity=lambda **_: SimpleNamespace(discord_user_id=99, is_dispatcher=True, is_admin=False)
        ),
        dispatch_service=SimpleNamespace(
            get_dispatch_attention_item_payload=lambda **kwargs: asyncio.sleep(0, result=kwargs)
        ),
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="GET",
            path="/dispatch/attention/dispatch%3ASR-96224%3Apart_received",
            headers={"Authorization": "Bearer secret", "X-Dispatch-Subject": "99"},
        )
    )

    assert status == HTTPStatus.OK
    assert payload["item_id"] == "dispatch:SR-96224:part_received"


def test_dispatch_returns_sr_customer_payload() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        technician_api_service=SimpleNamespace(health=_health),
        technician_directory_service=SimpleNamespace(
            resolve_identity=lambda **_: SimpleNamespace(discord_user_id=99, is_dispatcher=True, is_admin=False)
        ),
        dispatch_service=SimpleNamespace(
            get_dispatch_sr_customer_payload=lambda **_: asyncio.sleep(0, result={"reference": "SR-100", "customerName": "Pat"})
        ),
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="GET",
            path="/dispatch/sr/100/customer",
            headers={"Authorization": "Bearer secret", "X-Dispatch-Subject": "99"},
        )
    )

    assert status == HTTPStatus.OK
    assert payload == {"reference": "SR-100", "customerName": "Pat"}


def test_dispatch_returns_sr_timeline_payload() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        technician_api_service=SimpleNamespace(health=_health),
        technician_directory_service=SimpleNamespace(
            resolve_identity=lambda **_: SimpleNamespace(discord_user_id=99, is_dispatcher=True, is_admin=False)
        ),
        dispatch_service=SimpleNamespace(
            get_dispatch_sr_timeline_payload=lambda **_: asyncio.sleep(0, result={"reference": "SR-100", "entries": []})
        ),
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="GET",
            path="/dispatch/sr/100/timeline",
            headers={"Authorization": "Bearer secret", "X-Dispatch-Subject": "99"},
        )
    )

    assert status == HTTPStatus.OK
    assert payload == {"reference": "SR-100", "entries": []}


def test_dispatch_returns_sr_sms_capabilities_payload() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        technician_api_service=SimpleNamespace(health=_health),
        technician_directory_service=SimpleNamespace(
            resolve_identity=lambda **_: SimpleNamespace(discord_user_id=99, is_dispatcher=True, is_admin=False)
        ),
        dispatch_service=SimpleNamespace(
            get_dispatch_sr_sms_capabilities_payload=lambda **_: asyncio.sleep(
                0,
                result={"provider": "dry_run", "enabled": True, "toNumber": "555-0100"},
            )
        ),
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="GET",
            path="/dispatch/sr/100/sms_capabilities",
            headers={"Authorization": "Bearer secret", "X-Dispatch-Subject": "99"},
        )
    )

    assert status == HTTPStatus.OK
    assert payload["enabled"] is True


def test_dispatch_previews_sr_sms() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        technician_api_service=SimpleNamespace(health=_health),
        technician_directory_service=SimpleNamespace(
            resolve_identity=lambda **_: SimpleNamespace(discord_user_id=99, is_dispatcher=True, is_admin=False)
        ),
        dispatch_service=SimpleNamespace(
            preview_dispatch_sr_sms_payload=lambda **_: asyncio.sleep(
                0,
                result={"provider": "dry_run", "message": "ARCoM Ops: Test"},
            )
        ),
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="POST",
            path="/dispatch/sr/100/sms/preview",
            headers={"Authorization": "Bearer secret", "X-Dispatch-Subject": "99"},
            body={"intent": "dispatch_follow_up"},
        )
    )

    assert status == HTTPStatus.OK
    assert payload["provider"] == "dry_run"


def test_parts_returns_board_payload() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        technician_api_service=SimpleNamespace(health=_health),
        technician_directory_service=SimpleNamespace(
            resolve_identity=lambda **_: SimpleNamespace(discord_user_id=77, is_parts=True, is_admin=False)
        ),
        parts_cannon_service=SimpleNamespace(
            get_parts_board_payload=lambda: asyncio.sleep(0, result={"queueSummary": {"openRequests": 2}})
        ),
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="GET",
            path="/parts/board",
            headers={"Authorization": "Bearer secret", "X-Parts-Subject": "77"},
        )
    )

    assert status == HTTPStatus.OK
    assert payload["queueSummary"]["openRequests"] == 2


def test_parts_returns_cases_payload() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        technician_api_service=SimpleNamespace(health=_health),
        technician_directory_service=SimpleNamespace(
            resolve_identity=lambda **_: SimpleNamespace(discord_user_id=77, is_parts=True, is_admin=False)
        ),
        parts_cannon_service=SimpleNamespace(
            get_parts_cases_payload=lambda **_: asyncio.sleep(0, result={"items": [{"reference": "SR-100"}]})
        ),
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="GET",
            path="/parts/cases?stage=part_ready",
            headers={"Authorization": "Bearer secret", "X-Parts-Subject": "77"},
        )
    )

    assert status == HTTPStatus.OK
    assert payload["items"][0]["reference"] == "SR-100"


def test_parts_returns_request_payload() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        technician_api_service=SimpleNamespace(health=_health),
        technician_directory_service=SimpleNamespace(
            resolve_identity=lambda **_: SimpleNamespace(discord_user_id=77, is_parts=True, is_admin=False)
        ),
        parts_cannon_service=SimpleNamespace(
            get_parts_request_payload=lambda **_: asyncio.sleep(0, result={"request": {"requestId": 5}})
        ),
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="GET",
            path="/parts/requests/5",
            headers={"Authorization": "Bearer secret", "X-Parts-Subject": "77"},
        )
    )

    assert status == HTTPStatus.OK
    assert payload["request"]["requestId"] == 5


def test_parts_returns_bad_request_when_case_detail_lookup_fails() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        technician_api_service=SimpleNamespace(health=_health),
        technician_directory_service=SimpleNamespace(
            resolve_identity=lambda **_: SimpleNamespace(discord_user_id=77, is_parts=True, is_admin=False)
        ),
        parts_cannon_service=SimpleNamespace(
            get_parts_case_payload=lambda **_: asyncio.sleep(0, result=(_ for _ in ()).throw(ValueError("Unknown parts case reference")))
        ),
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="GET",
            path="/parts/cases/SR-999",
            headers={"Authorization": "Bearer secret", "X-Parts-Subject": "77"},
        )
    )

    assert status == HTTPStatus.BAD_REQUEST
    assert payload == {"success": False, "message": "Unknown parts case reference"}


def test_parts_posts_request_claim() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        technician_api_service=SimpleNamespace(health=_health),
        technician_directory_service=SimpleNamespace(
            resolve_identity=lambda **_: SimpleNamespace(discord_user_id=77, is_parts=True, is_admin=False)
        ),
        parts_cannon_service=SimpleNamespace(
            claim_request_payload=lambda **kwargs: asyncio.sleep(0, result=kwargs)
        ),
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="POST",
            path="/parts/requests/5/claim",
            headers={"Authorization": "Bearer secret", "X-Parts-Subject": "77"},
            body={},
        )
    )

    assert status == HTTPStatus.OK
    assert payload["request_id"] == 5
    assert payload["parts_user_id"] == 77


def test_parts_posts_bluefolder_ready_update() -> None:
    settings = SimpleNamespace(technician_api_token="secret")
    container = SimpleNamespace(
        technician_api_service=SimpleNamespace(health=_health),
        technician_directory_service=SimpleNamespace(
            resolve_identity=lambda **_: SimpleNamespace(discord_user_id=77, is_parts=True, is_admin=False),
            discord_mention=lambda user_id: f"<@{user_id}>",
        ),
        parts_cannon_service=SimpleNamespace(),
        bluefolder_service=SimpleNamespace(
            log_parts_update=lambda *args, **kwargs: asyncio.sleep(
                0,
                result=SimpleNamespace(message=f"logged {kwargs['update_type']} for {args[0]}"),
            )
        ),
    )

    status, payload = asyncio.run(
        dispatch_technician_api_request(
            settings=settings,
            container=container,
            method="POST",
            path="/parts/sr/100/ready",
            headers={"Authorization": "Bearer secret", "X-Parts-Subject": "77"},
            body={"details": "Ready to schedule", "readyNote": "Call customer"},
        )
    )

    assert status == HTTPStatus.OK
    assert payload["srId"] == 100
    assert payload["updateType"] == "part_ready"
