"""Minimal HTTP server for the technician mobile app."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from ops_hub.core.config import Settings
from ops_hub.core.container import ServiceContainer


logger = logging.getLogger(__name__)


async def dispatch_technician_api_request(
    *,
    settings: Settings,
    container: ServiceContainer,
    method: str,
    path: str,
    headers: dict[str, str],
    body: dict[str, object] | None = None,
) -> tuple[HTTPStatus, object]:
    """Handle one technician API request without binding a real socket."""
    authorization = headers.get("Authorization") or ""
    if authorization != f"Bearer {settings.technician_api_token or ''}":
        return HTTPStatus.UNAUTHORIZED, {"success": False, "message": "Unauthorized"}

    parsed = urlparse(path)
    route_path = parsed.path.rstrip("/") or "/"
    query = parse_qs(parsed.query)

    if method == "GET" and route_path == "/health":
        return HTTPStatus.OK, await container.technician_api_service.health()

    if route_path.startswith("/dispatch"):
        dispatcher = _resolve_dispatcher_identity(
            container=container,
            dispatcher_subject=headers.get("X-Dispatch-Subject"),
            dispatcher_id=(query.get("dispatcher_id") or [None])[0],
        )
        if dispatcher is None:
            return HTTPStatus.FORBIDDEN, {"success": False, "message": "Dispatcher or admin identity could not be resolved."}
        dispatcher_user_id = dispatcher.discord_user_id

        if method == "GET" and route_path == "/dispatch/board":
            return HTTPStatus.OK, await container.dispatch_service.get_dispatch_board_payload()

        if method == "GET" and route_path == "/dispatch/attention":
            payload = await container.dispatch_service.get_dispatch_attention_payload(
                stage=(query.get("stage") or [None])[0],
                age=(query.get("age") or [None])[0],
                technician_bluefolder_user_id=_query_int(query, "bluefolder_user_id"),
                owner_discord_user_id=_query_int(query, "owner_discord_user_id"),
                status=(query.get("status") or [None])[0],
                reference=(query.get("reference") or [None])[0],
            )
            return HTTPStatus.OK, payload

        if method == "POST" and route_path == "/dispatch/attention/bulk":
            item_ids = body.get("itemIds") if isinstance(body, dict) else None
            if not isinstance(item_ids, list) or not all(isinstance(item_id, str) for item_id in item_ids):
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": "itemIds must be a list of attention item ids."}
            action = str((body or {}).get("action") or "")
            if not action:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": "action is required."}
            try:
                payload = await container.dispatch_service.apply_bulk_dispatch_attention_action(
                    item_ids=item_ids,
                    action=action,
                    actor_user_id=dispatcher_user_id,
                    action_body=body or {},
                )
            except ValueError as exc:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": str(exc)}
            return HTTPStatus.OK, payload

        if method == "POST" and route_path.startswith("/dispatch/triage/") and route_path.endswith("/disposition"):
            sr_id = _path_int(route_path, prefix="/dispatch/triage/", suffix="/disposition")
            if sr_id is None:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid service request id."}
            disposition = str((body or {}).get("disposition") or "")
            if not disposition:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": "disposition is required."}
            payload = await container.dispatch_service.set_dispatch_triage_disposition(
                sr_id=sr_id,
                disposition=disposition,
                actor_user_id=dispatcher_user_id,
                details=str((body or {}).get("details") or "") or None,
            )
            return HTTPStatus.OK, {"success": True, "message": payload.message, "srId": sr_id, "disposition": disposition}

        if method == "GET" and route_path.startswith("/dispatch/sr/"):
            if route_path.endswith("/timeline"):
                sr_id = _path_int(route_path, prefix="/dispatch/sr/", suffix="/timeline")
                if sr_id is None:
                    return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid service request id."}
                try:
                    return HTTPStatus.OK, await container.dispatch_service.get_dispatch_sr_timeline_payload(sr_id=sr_id)
                except ValueError as exc:
                    return HTTPStatus.BAD_REQUEST, {"success": False, "message": str(exc)}
            if route_path.endswith("/customer"):
                sr_id = _path_int(route_path, prefix="/dispatch/sr/", suffix="/customer")
                if sr_id is None:
                    return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid service request id."}
                return HTTPStatus.OK, await container.dispatch_service.get_dispatch_sr_customer_payload(sr_id=sr_id)
            if route_path.endswith("/work"):
                sr_id = _path_int(route_path, prefix="/dispatch/sr/", suffix="/work")
                if sr_id is None:
                    return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid service request id."}
                return HTTPStatus.OK, await container.dispatch_service.get_dispatch_sr_work_payload(sr_id=sr_id)

        if method == "GET" and route_path.startswith("/dispatch/attention/"):
            item_id = _path_tail(route_path, prefix="/dispatch/attention/")
            if not item_id:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid attention item id."}
            try:
                return HTTPStatus.OK, await container.dispatch_service.get_dispatch_attention_item_payload(item_id=item_id)
            except ValueError as exc:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": str(exc)}

        payload_body = body or {}
        if method == "POST" and route_path.startswith("/dispatch/attention/"):
            action_match = _path_action(route_path, prefix="/dispatch/attention/")
            if action_match is None:
                return HTTPStatus.NOT_FOUND, {"success": False, "message": "Not found"}
            item_id, action = action_match
            try:
                if action == "ack":
                    payload = await container.dispatch_service.acknowledge_dispatch_attention_item(
                        item_id=item_id,
                        actor_user_id=dispatcher_user_id,
                    )
                elif action == "snooze":
                    payload = await container.dispatch_service.snooze_dispatch_attention_item(
                        item_id=item_id,
                        hours=int(payload_body.get("hours") or 1),
                        actor_user_id=dispatcher_user_id,
                    )
                elif action == "unsnooze":
                    payload = await container.dispatch_service.unsnooze_dispatch_attention_item(
                        item_id=item_id,
                        actor_user_id=dispatcher_user_id,
                    )
                elif action == "reopen":
                    payload = await container.dispatch_service.reopen_dispatch_attention_item(
                        item_id=item_id,
                        actor_user_id=dispatcher_user_id,
                    )
                elif action == "assign":
                    assigned_owner_discord_user_id = int(payload_body.get("assignedOwnerDiscordUserId") or 0)
                    if assigned_owner_discord_user_id <= 0:
                        return HTTPStatus.BAD_REQUEST, {
                            "success": False,
                            "message": "assignedOwnerDiscordUserId must be a positive Discord user id.",
                        }
                    payload = await container.dispatch_service.assign_dispatch_attention_item(
                        item_id=item_id,
                        assigned_owner_discord_user_id=assigned_owner_discord_user_id,
                        actor_user_id=dispatcher_user_id,
                    )
                elif action == "clear_owner":
                    payload = await container.dispatch_service.clear_dispatch_attention_item_owner(
                        item_id=item_id,
                        actor_user_id=dispatcher_user_id,
                    )
                elif action == "triage_disposition":
                    disposition = str(payload_body.get("disposition") or "")
                    if not disposition:
                        return HTTPStatus.BAD_REQUEST, {"success": False, "message": "disposition is required."}
                    payload = await container.dispatch_service.set_dispatch_triage_disposition_item(
                        item_id=item_id,
                        disposition=disposition,
                        actor_user_id=dispatcher_user_id,
                        details=str(payload_body.get("details") or "") or None,
                    )
                else:
                    return HTTPStatus.NOT_FOUND, {"success": False, "message": "Not found"}
            except ValueError as exc:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": str(exc)}
            return HTTPStatus.OK, payload

        if method == "GET" and route_path == "/dispatch/routes/preview":
            bluefolder_user_id = _query_int(query, "bluefolder_user_id")
            if bluefolder_user_id is None:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": "bluefolder_user_id is required."}
            payload = await container.dispatch_service.get_dispatch_route_payload(
                technician_bluefolder_user_id=bluefolder_user_id,
                origin_address=(query.get("origin_address") or [None])[0],
                destination_address=(query.get("destination_address") or [None])[0],
            )
            return HTTPStatus.OK, payload

        if method == "GET" and route_path == "/dispatch/routes/heatmap":
            payload = await container.dispatch_service.get_dispatch_heatmap_payload(
                technician_bluefolder_user_id=_query_int(query, "bluefolder_user_id")
            )
            return HTTPStatus.OK, payload

        if method == "GET" and route_path == "/dispatch/intake/formats":
            return HTTPStatus.OK, container.service_smith_service.list_formats_payload()

        if method == "GET" and route_path == "/dispatch/intake/profiles":
            return HTTPStatus.OK, container.service_smith_service.list_profiles_payload()

        if method == "POST" and route_path == "/dispatch/intake/profiles":
            payload_body = body or {}
            try:
                return HTTPStatus.OK, container.service_smith_service.save_profile_payload(
                    name=str(payload_body.get("name") or ""),
                    format_name=str(payload_body.get("formatName") or "default"),
                    field_map_path=str(payload_body.get("fieldMapPath") or "").strip() or None,
                    row_start=int(payload_body["rowStart"]) if payload_body.get("rowStart") is not None else None,
                    row_end=int(payload_body["rowEnd"]) if payload_body.get("rowEnd") is not None else None,
                    limit=int(payload_body["limit"]) if payload_body.get("limit") is not None else 25,
                    duplicate_mode=str(payload_body.get("duplicateMode") or "skip"),
                    preview_mode=str(payload_body.get("previewMode") or "plan"),
                    fail_fast=bool(payload_body.get("failFast")),
                    actor_user_id=dispatcher_user_id,
                )
            except (RuntimeError, ValueError) as exc:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": str(exc)}

        if method == "DELETE" and route_path.startswith("/dispatch/intake/profiles/"):
            profile_name = _path_tail(route_path, prefix="/dispatch/intake/profiles/")
            if not profile_name:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid intake profile name."}
            try:
                return HTTPStatus.OK, container.service_smith_service.delete_profile_payload(name=profile_name)
            except (RuntimeError, ValueError) as exc:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": str(exc)}

        if method == "POST" and route_path == "/dispatch/intake/analyze":
            payload_body = body or {}
            spreadsheet_path = str(payload_body.get("spreadsheetPath") or "").strip()
            if not spreadsheet_path:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": "spreadsheetPath is required."}
            try:
                return HTTPStatus.OK, container.service_smith_service.analyze_spreadsheet_payload(
                    spreadsheet_path=spreadsheet_path,
                    format_name=str(payload_body.get("format") or "default"),
                    field_map_path=str(payload_body.get("fieldMapPath") or "").strip() or None,
                    row_start=int(payload_body["rowStart"]) if payload_body.get("rowStart") is not None else None,
                    row_end=int(payload_body["rowEnd"]) if payload_body.get("rowEnd") is not None else None,
                    limit=int(payload_body["limit"]) if payload_body.get("limit") is not None else 25,
                )
            except (RuntimeError, ValueError) as exc:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": str(exc)}

        if method == "POST" and route_path == "/dispatch/intake/preview":
            payload_body = body or {}
            spreadsheet_path = str(payload_body.get("spreadsheetPath") or "").strip()
            if not spreadsheet_path:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": "spreadsheetPath is required."}
            try:
                return HTTPStatus.OK, container.service_smith_service.preview_import_payload(
                    spreadsheet_path=spreadsheet_path,
                    format_name=str(payload_body.get("format") or "default"),
                    field_map_path=str(payload_body.get("fieldMapPath") or "").strip() or None,
                    duplicate_mode=str(payload_body.get("duplicateMode") or "skip"),
                    preview_mode=str(payload_body.get("previewMode") or "plan"),
                    row_start=int(payload_body["rowStart"]) if payload_body.get("rowStart") is not None else None,
                    row_end=int(payload_body["rowEnd"]) if payload_body.get("rowEnd") is not None else None,
                    limit=int(payload_body["limit"]) if payload_body.get("limit") is not None else 25,
                )
            except (RuntimeError, ValueError) as exc:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": str(exc)}

        if method == "POST" and route_path == "/dispatch/intake/import":
            payload_body = body or {}
            spreadsheet_path = str(payload_body.get("spreadsheetPath") or "").strip()
            if not spreadsheet_path:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": "spreadsheetPath is required."}
            try:
                return HTTPStatus.OK, container.service_smith_service.import_spreadsheet_payload(
                    spreadsheet_path=spreadsheet_path,
                    format_name=str(payload_body.get("format") or "default"),
                    field_map_path=str(payload_body.get("fieldMapPath") or "").strip() or None,
                    duplicate_mode=str(payload_body.get("duplicateMode") or "skip"),
                    row_start=int(payload_body["rowStart"]) if payload_body.get("rowStart") is not None else None,
                    row_end=int(payload_body["rowEnd"]) if payload_body.get("rowEnd") is not None else None,
                    limit=int(payload_body["limit"]) if payload_body.get("limit") is not None else None,
                    fail_fast=bool(payload_body.get("failFast")),
                )
            except (RuntimeError, ValueError) as exc:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": str(exc)}

    if route_path.startswith("/parts"):
        parts_user = _resolve_parts_identity(
            container=container,
            parts_subject=headers.get("X-Parts-Subject"),
            parts_id=(query.get("parts_user_id") or [None])[0],
        )
        if parts_user is None:
            return HTTPStatus.FORBIDDEN, {"success": False, "message": "Parts or admin identity could not be resolved."}
        parts_user_id = parts_user.discord_user_id

        if method == "GET" and route_path == "/parts/board":
            return HTTPStatus.OK, await container.parts_cannon_service.get_parts_board_payload()

        if method == "GET" and route_path == "/parts/cases":
            return HTTPStatus.OK, await container.parts_cannon_service.get_parts_cases_payload(
                stage=(query.get("stage") or [None])[0],
                age=(query.get("age") or [None])[0],
                assigned_parts_user_id=_query_int(query, "assigned_parts_user_id"),
                status=(query.get("status") or [None])[0],
                reference=(query.get("reference") or [None])[0],
            )

        if method == "GET" and route_path.startswith("/parts/cases/"):
            if route_path.endswith("/timeline"):
                reference = _path_tail(route_path[: -len("/timeline")], prefix="/parts/cases/")
                if not reference:
                    return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid parts case reference."}
                return HTTPStatus.OK, await container.parts_cannon_service.get_parts_case_timeline_payload(reference=reference)
            reference = _path_tail(route_path, prefix="/parts/cases/")
            if not reference:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid parts case reference."}
            return HTTPStatus.OK, await container.parts_cannon_service.get_parts_case_payload(reference=reference)

        if method == "GET" and route_path == "/parts/requests":
            return HTTPStatus.OK, await container.parts_cannon_service.get_parts_requests_payload(
                status=(query.get("status") or [None])[0],
                assigned_parts_user_id=_query_int(query, "assigned_parts_user_id"),
                requested_by_user_id=_query_int(query, "requested_by_user_id"),
                reference=(query.get("reference") or [None])[0],
                only_unsynced=((query.get("only_unsynced") or ["false"])[0].strip().lower() == "true"),
            )

        if method == "GET" and route_path.startswith("/parts/requests/"):
            request_id = _path_int(route_path, prefix="/parts/requests/")
            if request_id is None:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid parts request id."}
            try:
                return HTTPStatus.OK, await container.parts_cannon_service.get_parts_request_payload(request_id=request_id)
            except ValueError as exc:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": str(exc)}

        payload_body = body or {}
        if method == "POST" and route_path == "/parts/requests/sync":
            return HTTPStatus.OK, await container.parts_cannon_service.sync_requests_payload()

        if method == "POST" and route_path == "/parts/requests/reconcile":
            return HTTPStatus.OK, await container.parts_cannon_service.reconcile_requests_payload()

        if method == "POST" and route_path.startswith("/parts/requests/"):
            action_match = _path_action(route_path, prefix="/parts/requests/")
            if action_match is None:
                return HTTPStatus.NOT_FOUND, {"success": False, "message": "Not found"}
            request_id_text, action = action_match
            if not request_id_text.isdigit():
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid parts request id."}
            request_id = int(request_id_text)
            try:
                if action == "claim":
                    assigned_parts_user_id = payload_body.get("assignedPartsUserId")
                    if assigned_parts_user_id is not None and not isinstance(assigned_parts_user_id, int):
                        return HTTPStatus.BAD_REQUEST, {
                            "success": False,
                            "message": "assignedPartsUserId must be an integer when provided.",
                        }
                    payload = await container.parts_cannon_service.claim_request_payload(
                        request_id=request_id,
                        parts_user_id=assigned_parts_user_id if isinstance(assigned_parts_user_id, int) else parts_user_id,
                        actor_user_id=parts_user_id,
                    )
                elif action == "unclaim":
                    payload = await container.parts_cannon_service.claim_request_payload(
                        request_id=request_id,
                        parts_user_id=None,
                        actor_user_id=parts_user_id,
                    )
                elif action == "status":
                    status_value = str(payload_body.get("status") or "")
                    if not status_value:
                        return HTTPStatus.BAD_REQUEST, {"success": False, "message": "status is required."}
                    payload = await container.parts_cannon_service.update_request_payload(
                        request_id=request_id,
                        status=status_value,
                        actor_user_id=parts_user_id,
                    )
                else:
                    return HTTPStatus.NOT_FOUND, {"success": False, "message": "Not found"}
            except ValueError as exc:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": str(exc)}
            return HTTPStatus.OK, payload

        if method == "POST" and route_path.startswith("/parts/sr/"):
            action_match = _path_action(route_path, prefix="/parts/sr/")
            if action_match is None:
                return HTTPStatus.NOT_FOUND, {"success": False, "message": "Not found"}
            sr_id_text, action = action_match
            if not sr_id_text.isdigit():
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid service request id."}
            sr_id = int(sr_id_text)

            update_type = None
            details = None
            metadata = None
            if action == "ordered":
                vendor = str(payload_body.get("vendor") or "").strip()
                if not vendor:
                    return HTTPStatus.BAD_REQUEST, {"success": False, "message": "vendor is required."}
                update_type = "part_ordered"
                details = str(payload_body.get("details") or "Order submitted.")
                metadata = {"vendor": vendor}
                eta_value = str(payload_body.get("eta") or "").strip()
                if eta_value:
                    metadata["eta"] = eta_value
            elif action == "eta":
                eta_value = str(payload_body.get("eta") or "").strip()
                if not eta_value:
                    return HTTPStatus.BAD_REQUEST, {"success": False, "message": "eta is required."}
                update_type = "part_eta"
                details = str(payload_body.get("details") or "ETA updated.")
                metadata = {"eta": eta_value}
                carrier = str(payload_body.get("carrier") or "").strip()
                if carrier:
                    metadata["carrier"] = carrier
            elif action == "tracking":
                tracking_number = str(payload_body.get("trackingNumber") or "").strip()
                if not tracking_number:
                    return HTTPStatus.BAD_REQUEST, {"success": False, "message": "trackingNumber is required."}
                update_type = "part_tracking"
                details = str(payload_body.get("details") or "Tracking posted.")
                metadata = {"tracking_number": tracking_number}
                carrier = str(payload_body.get("carrier") or "").strip()
                eta_value = str(payload_body.get("eta") or "").strip()
                if carrier:
                    metadata["carrier"] = carrier
                if eta_value:
                    metadata["eta"] = eta_value
            elif action == "received":
                update_type = "part_received"
                details = str(payload_body.get("details") or "")
                if not details:
                    return HTTPStatus.BAD_REQUEST, {"success": False, "message": "details is required."}
                received_from = str(payload_body.get("receivedFrom") or "").strip()
                metadata = {"received_from": received_from} if received_from else None
            elif action == "ready":
                update_type = "part_ready"
                details = str(payload_body.get("details") or "")
                if not details:
                    return HTTPStatus.BAD_REQUEST, {"success": False, "message": "details is required."}
                ready_note = str(payload_body.get("readyNote") or "").strip()
                metadata = {"ready_note": ready_note} if ready_note else None
            else:
                return HTTPStatus.NOT_FOUND, {"success": False, "message": "Not found"}

            result = await container.bluefolder_service.log_parts_update(
                sr_id,
                update_type=update_type,
                details=details,
                requested_by_user_id=parts_user_id,
                requested_by_label=container.technician_directory_service.discord_mention(parts_user_id),
                metadata=metadata,
            )
            return HTTPStatus.OK, {
                "success": True,
                "message": result.message,
                "srId": sr_id,
                "updateType": update_type,
            }

    technician = container.technician_api_service.resolve_technician(
        token_subject=headers.get("X-Technician-Subject"),
        technician_id=(query.get("technician_id") or [None])[0],
    )
    if technician is None:
        return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Technician mapping could not be resolved."}
    discord_user_id, bluefolder_user_id = technician

    if method == "GET" and route_path == "/tech/me/today":
        payload = await container.technician_api_service.get_today(
            technician_bluefolder_user_id=bluefolder_user_id
        )
        return HTTPStatus.OK, payload

    if method == "GET" and route_path == "/tech/jobs":
        payload = await container.technician_api_service.get_jobs(
            technician_bluefolder_user_id=bluefolder_user_id,
            start=(query.get("start") or [None])[0],
            end=(query.get("end") or [None])[0],
            date_range_type=(query.get("type") or ["scheduled"])[0],
        )
        return HTTPStatus.OK, payload

    if method == "GET" and route_path.startswith("/tech/jobs/"):
        if route_path.endswith("/photos"):
            sr_id = _path_int(route_path, prefix="/tech/jobs/", suffix="/photos")
            if sr_id is None:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid service request id."}
            return HTTPStatus.OK, await container.technician_api_service.get_job_photo_status(sr_id=sr_id)

        if route_path.endswith("/parts"):
            sr_id = _path_int(route_path, prefix="/tech/jobs/", suffix="/parts")
            if sr_id is None:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid service request id."}
            return HTTPStatus.OK, await container.technician_api_service.get_job_parts_case(sr_id=sr_id)

        if route_path.endswith("/timeline"):
            sr_id = _path_int(route_path, prefix="/tech/jobs/", suffix="/timeline")
            if sr_id is None:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid service request id."}
            return HTTPStatus.OK, await container.technician_api_service.get_job_timeline(sr_id=sr_id)

        sr_id = _path_int(route_path, prefix="/tech/jobs/")
        if sr_id is None:
            return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid service request id."}
        return HTTPStatus.OK, await container.technician_api_service.get_job(sr_id=sr_id)

    payload_body = body or {}
    if method == "POST" and route_path.endswith("/status"):
        sr_id = _path_int(route_path, prefix="/tech/jobs/", suffix="/status")
        if sr_id is None:
            return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid service request id."}
        payload = await container.technician_api_service.update_status(
            sr_id=sr_id,
            technician_discord_user_id=discord_user_id,
            technician_bluefolder_user_id=bluefolder_user_id,
            status=str(payload_body.get("status") or ""),
        )
        return HTTPStatus.OK, payload

    if method == "POST" and route_path.endswith("/notes"):
        sr_id = _path_int(route_path, prefix="/tech/jobs/", suffix="/notes")
        if sr_id is None:
            return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid service request id."}
        payload = await container.technician_api_service.submit_note(
            sr_id=sr_id,
            note=str(payload_body.get("note") or ""),
            technician_discord_user_id=discord_user_id,
            technician_bluefolder_user_id=bluefolder_user_id,
        )
        return HTTPStatus.OK, payload

    if method == "POST" and route_path.endswith("/parts"):
        sr_id = _path_int(route_path, prefix="/tech/jobs/", suffix="/parts")
        if sr_id is None:
            return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid service request id."}
        payload = await container.technician_api_service.create_parts_request(
            sr_id=sr_id,
            details=str(payload_body.get("details") or ""),
            technician_discord_user_id=discord_user_id,
            technician_bluefolder_user_id=bluefolder_user_id,
        )
        return HTTPStatus.OK, payload

    if method == "POST" and route_path.endswith("/call_ahead"):
        sr_id = _path_int(route_path, prefix="/tech/jobs/", suffix="/call_ahead")
        if sr_id is None:
            return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid service request id."}
        payload = await container.technician_api_service.log_call_ahead(
            sr_id=sr_id,
            technician_discord_user_id=discord_user_id,
            technician_bluefolder_user_id=bluefolder_user_id,
            minutes=payload_body.get("minutes") if isinstance(payload_body.get("minutes"), int) else None,
        )
        return HTTPStatus.OK, payload

    if method == "POST" and route_path.endswith("/start"):
        sr_id = _path_int(route_path, prefix="/tech/jobs/", suffix="/start")
        if sr_id is None:
            return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid service request id."}
        payload = await container.technician_api_service.log_work_start(
            sr_id=sr_id,
            details=str(payload_body.get("details") or "") or None,
            technician_discord_user_id=discord_user_id,
            technician_bluefolder_user_id=bluefolder_user_id,
        )
        return HTTPStatus.OK, payload

    if method == "POST" and route_path.endswith("/no_answer"):
        sr_id = _path_int(route_path, prefix="/tech/jobs/", suffix="/no_answer")
        if sr_id is None:
            return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid service request id."}
        payload = await container.technician_api_service.report_no_answer(
            sr_id=sr_id,
            details=str(payload_body.get("details") or ""),
            technician_discord_user_id=discord_user_id,
            technician_bluefolder_user_id=bluefolder_user_id,
        )
        return HTTPStatus.OK, payload

    if method == "POST" and route_path.endswith("/not_home"):
        sr_id = _path_int(route_path, prefix="/tech/jobs/", suffix="/not_home")
        if sr_id is None:
            return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid service request id."}
        payload = await container.technician_api_service.report_not_home(
            sr_id=sr_id,
            details=str(payload_body.get("details") or ""),
            technician_discord_user_id=discord_user_id,
            technician_bluefolder_user_id=bluefolder_user_id,
        )
        return HTTPStatus.OK, payload

    if method == "POST" and route_path.endswith("/quote_needed"):
        sr_id = _path_int(route_path, prefix="/tech/jobs/", suffix="/quote_needed")
        if sr_id is None:
            return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid service request id."}
        payload = await container.technician_api_service.report_quote_needed(
            sr_id=sr_id,
            details=str(payload_body.get("details") or ""),
            subtype=str(payload_body.get("subtype") or ""),
            technician_discord_user_id=discord_user_id,
            technician_bluefolder_user_id=bluefolder_user_id,
        )
        return HTTPStatus.OK, payload

    if method == "POST" and route_path.endswith("/reschedule"):
        sr_id = _path_int(route_path, prefix="/tech/jobs/", suffix="/reschedule")
        if sr_id is None:
            return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid service request id."}
        payload = await container.technician_api_service.report_reschedule_needed(
            sr_id=sr_id,
            reason=str(payload_body.get("reason") or ""),
            technician_discord_user_id=discord_user_id,
            technician_bluefolder_user_id=bluefolder_user_id,
        )
        return HTTPStatus.OK, payload

    if method == "POST" and route_path.endswith("/unable_to_complete"):
        sr_id = _path_int(route_path, prefix="/tech/jobs/", suffix="/unable_to_complete")
        if sr_id is None:
            return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid service request id."}
        payload = await container.technician_api_service.report_unable_to_complete(
            sr_id=sr_id,
            reason=str(payload_body.get("reason") or ""),
            technician_discord_user_id=discord_user_id,
            technician_bluefolder_user_id=bluefolder_user_id,
        )
        return HTTPStatus.OK, payload

    if method == "POST" and route_path.endswith("/photo_compliance"):
        sr_id = _path_int(route_path, prefix="/tech/jobs/", suffix="/photo_compliance")
        if sr_id is None:
            return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid service request id."}
        payload = await container.technician_api_service.evaluate_job_photo_compliance(
            sr_id=sr_id,
            status_override=str(payload_body.get("statusOverride") or "") or None,
            send_notice=bool(payload_body.get("sendNotice")),
        )
        return HTTPStatus.OK, payload

    if method == "POST" and route_path.endswith("/photos/prepare"):
        sr_id = _path_int(route_path, prefix="/tech/jobs/", suffix="/photos/prepare")
        if sr_id is None:
            return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid service request id."}
        payload = await container.technician_api_service.prepare_photo_upload(
            sr_id=sr_id,
            label=str(payload_body.get("label") or ""),
        )
        return HTTPStatus.OK, payload

    return HTTPStatus.NOT_FOUND, {"success": False, "message": "Not found"}


def _resolve_dispatcher_identity(*, container: ServiceContainer, dispatcher_subject: str | None, dispatcher_id: str | None):
    """Resolve a dispatch or admin caller from header/query context."""
    raw_user_id = None
    if dispatcher_id and dispatcher_id.isdigit():
        raw_user_id = int(dispatcher_id)
    elif dispatcher_subject and dispatcher_subject.isdigit():
        raw_user_id = int(dispatcher_subject)
    if raw_user_id is None:
        return None
    identity = container.technician_directory_service.resolve_identity(user_id=raw_user_id, role_ids=set())
    if not (identity.is_dispatcher or identity.is_admin):
        return None
    return identity


def _resolve_parts_identity(*, container: ServiceContainer, parts_subject: str | None, parts_id: str | None):
    """Resolve a parts or admin caller from header/query context."""
    raw_user_id = None
    if parts_id and parts_id.isdigit():
        raw_user_id = int(parts_id)
    elif parts_subject and parts_subject.isdigit():
        raw_user_id = int(parts_subject)
    if raw_user_id is None:
        return None
    identity = container.technician_directory_service.resolve_identity(user_id=raw_user_id, role_ids=set())
    if not (identity.is_parts or identity.is_admin):
        return None
    return identity


def _query_int(query: dict[str, list[str]], key: str) -> int | None:
    """Parse one optional positive integer query parameter."""
    value = (query.get(key) or [None])[0]
    return int(value) if isinstance(value, str) and value.isdigit() else None


def _path_int(path: str, *, prefix: str, suffix: str = "") -> int | None:
    """Parse an integer id from a technician API route."""
    candidate = path
    if suffix and candidate.endswith(suffix):
        candidate = candidate[: -len(suffix)]
    if not candidate.startswith(prefix):
        return None
    value = candidate[len(prefix):].strip("/")
    return int(value) if value.isdigit() else None


def _path_tail(path: str, *, prefix: str) -> str | None:
    """Parse a trailing path segment as a raw string value."""
    if not path.startswith(prefix):
        return None
    value = path[len(prefix):].strip("/")
    return value or None


def _path_action(path: str, *, prefix: str) -> tuple[str, str] | None:
    """Parse /prefix/<item_id>/<action> paths."""
    if not path.startswith(prefix):
        return None
    remainder = path[len(prefix):].strip("/")
    if "/" not in remainder:
        return None
    item_id, action = remainder.rsplit("/", 1)
    if not item_id or not action:
        return None
    return item_id, action


@dataclass(slots=True)
class TechnicianApiServer:
    """Background HTTP server wrapper for app-facing routes."""

    settings: Settings
    container: ServiceContainer
    httpd: ThreadingHTTPServer | None = None
    thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the technician API server in a background thread."""
        if not self.settings.enable_technician_api:
            return
        server = ThreadingHTTPServer(
            (self.settings.technician_api_host, self.settings.technician_api_port),
            self._build_handler(),
        )
        self.httpd = server
        self.thread = threading.Thread(target=server.serve_forever, name="ops-hub-technician-api", daemon=True)
        self.thread.start()
        logger.info(
            "Technician API server started",
            extra={"host": self.settings.technician_api_host, "port": self.settings.technician_api_port},
        )

    def stop(self) -> None:
        """Stop the background HTTP server."""
        if self.httpd is None:
            return
        self.httpd.shutdown()
        self.httpd.server_close()
        self.httpd = None
        self.thread = None

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        settings = self.settings
        container = self.container

        class Handler(BaseHTTPRequestHandler):
            server_version = "OpsHubTechnicianAPI/0.1"

            def do_GET(self) -> None:  # noqa: N802
                self._dispatch("GET")

            def do_POST(self) -> None:  # noqa: N802
                self._dispatch("POST")

            def log_message(self, format: str, *args: object) -> None:
                logger.info("Technician API " + format, *args)

            def _dispatch(self, method: str) -> None:
                try:
                    status, payload = asyncio.run(
                        dispatch_technician_api_request(
                            settings=settings,
                            container=container,
                            method=method,
                            path=self.path,
                            headers={key: value for key, value in self.headers.items()},
                            body=self._read_json() if method == "POST" else None,
                        )
                    )
                    self._json(status, payload)
                except Exception as exc:
                    logger.exception("Technician API request failed")
                    self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"success": False, "message": str(exc)})

            def _read_json(self) -> dict[str, object]:
                length = int(self.headers.get("Content-Length") or "0")
                if length <= 0:
                    return {}
                raw = self.rfile.read(length).decode("utf-8")
                return json.loads(raw) if raw.strip() else {}

            def _json(self, status: HTTPStatus, payload: object) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler


def build_api_server(*, settings: Settings, container: ServiceContainer) -> TechnicianApiServer:
    """Construct the technician API server wrapper."""
    return TechnicianApiServer(settings=settings, container=container)
