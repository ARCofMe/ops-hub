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
                else:
                    return HTTPStatus.NOT_FOUND, {"success": False, "message": "Not found"}
            except ValueError as exc:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": str(exc)}
            return HTTPStatus.OK, payload

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
