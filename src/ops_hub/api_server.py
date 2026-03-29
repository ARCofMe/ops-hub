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


def _path_int(path: str, *, prefix: str, suffix: str = "") -> int | None:
    """Parse an integer id from a technician API route."""
    candidate = path
    if suffix and candidate.endswith(suffix):
        candidate = candidate[: -len(suffix)]
    if not candidate.startswith(prefix):
        return None
    value = candidate[len(prefix):].strip("/")
    return int(value) if value.isdigit() else None


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
