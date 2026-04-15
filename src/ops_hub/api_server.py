"""Minimal HTTP server for the technician mobile app."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import tempfile
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from ops_hub.core.config import Settings
from ops_hub.core.container import ServiceContainer


logger = logging.getLogger(__name__)


def build_ecosystem_status_payload() -> dict[str, object]:
    """Return a stable app-facing summary of the OpsHub ecosystem surfaces."""
    return {
        "success": True,
        "ecosystem": "OpsHub",
        "role": "brain",
        "frontends": [
            {
                "key": "routeDesk",
                "name": "RouteDesk",
                "role": "dispatch",
                "status": "ready",
                "url": "https://routedesk.ops-hub.org",
            },
            {
                "key": "partsDesk",
                "name": "PartsDesk",
                "role": "parts",
                "status": "ready",
                "url": "https://partsdesk.ops-hub.org",
            },
            {
                "key": "fieldDesk",
                "name": "FieldDesk",
                "role": "field",
                "status": "ready",
                "url": None,
            },
        ],
        "capabilities": [
            "dispatch_attention",
            "route_planning",
            "parts_tracking",
            "field_execution",
            "photo_compliance",
        ],
    }


def render_landing_page() -> str:
    """Return the public OpsHub landing page HTML."""
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OpsHub | Service Operations Command Center</title>
  <meta name="description" content="OpsHub connects dispatch, parts, and field execution into one service operations brain.">
  <style>
    :root {
      color-scheme: dark;
      --ink: #f8fbff;
      --muted: #a9b8c9;
      --panel: rgba(8, 16, 25, 0.76);
      --line: rgba(255, 255, 255, 0.14);
      --gold: #f2c84b;
      --green: #00a86b;
      --blue: #5fd8ff;
      --night: #03111d;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      min-height: 100vh;
      font-family: "Aptos Display", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 14% 18%, rgba(95, 216, 255, 0.25), transparent 28rem),
        radial-gradient(circle at 84% 12%, rgba(242, 200, 75, 0.2), transparent 22rem),
        linear-gradient(135deg, #02070d 0%, #062233 48%, #03111d 100%);
      overflow-x: hidden;
    }

    body::before {
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background:
        linear-gradient(rgba(255, 255, 255, 0.035) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255, 255, 255, 0.035) 1px, transparent 1px);
      background-size: 44px 44px;
      mask-image: linear-gradient(to bottom, black, transparent 88%);
    }

    main {
      width: min(1180px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 40px 0 56px;
      position: relative;
    }

    nav {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 20px;
      margin-bottom: 76px;
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      font-weight: 900;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .mark {
      width: 42px;
      height: 42px;
      border-radius: 14px;
      display: grid;
      place-items: center;
      color: #04110c;
      background: linear-gradient(135deg, var(--gold), var(--green));
      box-shadow: 0 18px 46px rgba(0, 168, 107, 0.35);
    }

    .navlinks {
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 10px;
    }

    a {
      color: inherit;
      text-decoration: none;
    }

    .pill {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 10px 14px;
      color: var(--muted);
      background: rgba(255, 255, 255, 0.06);
      backdrop-filter: blur(12px);
    }

    .hero {
      display: grid;
      grid-template-columns: 1.15fr 0.85fr;
      gap: 42px;
      align-items: center;
    }

    .eyebrow {
      color: var(--gold);
      font-weight: 800;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      margin: 0 0 18px;
    }

    h1 {
      margin: 0;
      font-size: clamp(3.4rem, 8vw, 7.7rem);
      line-height: 0.82;
      letter-spacing: -0.08em;
      max-width: 780px;
    }

    .copy {
      margin: 28px 0 0;
      max-width: 680px;
      color: #d7e4ef;
      font-size: clamp(1.1rem, 2vw, 1.35rem);
      line-height: 1.58;
    }

    .cta {
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
      margin-top: 34px;
    }

    .button {
      border-radius: 18px;
      padding: 15px 18px;
      font-weight: 900;
      border: 1px solid transparent;
    }

    .button.primary {
      color: #06120c;
      background: linear-gradient(135deg, var(--gold), #37df91);
      box-shadow: 0 18px 44px rgba(55, 223, 145, 0.25);
    }

    .button.secondary {
      color: var(--ink);
      border-color: var(--line);
      background: rgba(255, 255, 255, 0.08);
    }

    .console {
      min-height: 480px;
      border: 1px solid var(--line);
      border-radius: 34px;
      background: linear-gradient(160deg, rgba(8, 16, 25, 0.92), rgba(2, 7, 13, 0.7));
      box-shadow: 0 32px 90px rgba(0, 0, 0, 0.42);
      padding: 24px;
      position: relative;
      overflow: hidden;
    }

    .console::after {
      content: "";
      position: absolute;
      width: 210px;
      height: 210px;
      right: -62px;
      bottom: -72px;
      border-radius: 999px;
      background: radial-gradient(circle, rgba(0, 168, 107, 0.5), transparent 68%);
    }

    .status {
      display: grid;
      gap: 14px;
      position: relative;
      z-index: 1;
    }

    .card {
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 18px;
      background: rgba(255, 255, 255, 0.055);
    }

    .card strong {
      display: block;
      font-size: 1.05rem;
      margin-bottom: 8px;
    }

    .card span {
      color: var(--muted);
      line-height: 1.5;
    }

    .metric {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 12px;
      margin-top: 18px;
    }

    .metric div {
      border-radius: 18px;
      padding: 16px;
      background: rgba(95, 216, 255, 0.08);
      border: 1px solid rgba(95, 216, 255, 0.16);
    }

    .metric b {
      display: block;
      font-size: 1.7rem;
      color: var(--blue);
    }

    section {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 16px;
      margin-top: 46px;
    }

    section .card {
      min-height: 178px;
    }

    footer {
      color: var(--muted);
      margin-top: 48px;
      font-size: 0.95rem;
    }

    @media (max-width: 860px) {
      main { padding-top: 24px; }
      nav { align-items: flex-start; margin-bottom: 42px; }
      .hero, section { grid-template-columns: 1fr; }
      .console { min-height: auto; }
      .metric { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main>
    <nav>
      <a class="brand" href="/" aria-label="OpsHub home">
        <span class="mark">OH</span>
        <span>OpsHub</span>
      </a>
      <div class="navlinks" aria-label="Workspace links">
        <a class="pill" href="https://routedesk.ops-hub.org">RouteDesk</a>
        <a class="pill" href="https://partsdesk.ops-hub.org">PartsDesk</a>
        <span class="pill">FieldDesk Ready</span>
      </div>
    </nav>

    <div class="hero">
      <div>
        <p class="eyebrow">Service operations brain</p>
        <h1>Dispatch, parts, and field execution in one command layer.</h1>
        <p class="copy">
          OpsHub coordinates RouteDesk, PartsDesk, and FieldDesk so service teams can move from incoming work to
          technician-ready execution without losing context between systems.
        </p>
        <div class="cta">
          <a class="button primary" href="https://routedesk.ops-hub.org">Open RouteDesk</a>
          <a class="button secondary" href="https://partsdesk.ops-hub.org">Open PartsDesk</a>
        </div>
      </div>

      <aside class="console" aria-label="OpsHub platform overview">
        <div class="status">
          <div class="card">
            <strong>RouteDesk</strong>
            <span>Dispatch board, attention queue, SR context, route planning, and intake triage.</span>
          </div>
          <div class="card">
            <strong>PartsDesk</strong>
            <span>Parts cases, requests, readiness tracking, and dispatch handoff context.</span>
          </div>
          <div class="card">
            <strong>FieldDesk</strong>
            <span>Technician workflow, service-window order, notes, photos, closeout, and job execution assists.</span>
          </div>
          <div class="metric" aria-label="Platform pillars">
            <div><b>1</b><span>brain</span></div>
            <div><b>3</b><span>frontends</span></div>
            <div><b>0</b><span>context gaps</span></div>
          </div>
        </div>
      </aside>
    </div>

    <section aria-label="OpsHub outcomes">
      <div class="card">
        <strong>Live operations visibility</strong>
        <span>See work pressure, attention items, parts blockers, and technician-ready context in one ecosystem.</span>
      </div>
      <div class="card">
        <strong>Cleaner handoffs</strong>
        <span>Move from dispatch to parts to the field without retyping job context or guessing ownership.</span>
      </div>
      <div class="card">
        <strong>Presentation-safe workflow</strong>
        <span>Built for repeatable demos, release preflight checks, and field access through the production tunnel.</span>
      </div>
    </section>

    <footer>
      OpsHub API routes are authenticated. If you are configuring a tablet or workspace, use the technician API token from the OpsHub environment.
    </footer>
  </main>
</body>
</html>"""


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

    if method == "GET" and route_path == "/ecosystem/status":
        return HTTPStatus.OK, build_ecosystem_status_payload()

    if method == "GET" and route_path == "/bluefolder/status_catalog":
        return HTTPStatus.OK, container.bluefolder_service.get_status_catalog_payload()

    if route_path.startswith("/dispatch"):
        dispatcher = _resolve_dispatcher_identity(
            container=container,
            dispatcher_subject=headers.get("X-Dispatch-Subject"),
            dispatcher_id=(query.get("dispatcher_id") or [None])[0],
        )
        if dispatcher is None:
            return HTTPStatus.FORBIDDEN, {"success": False, "message": "Dispatcher or admin identity could not be resolved."}
        dispatcher_user_id = _identity_actor_user_id(dispatcher)

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
                try:
                    return HTTPStatus.OK, await container.dispatch_service.get_dispatch_sr_customer_payload(sr_id=sr_id)
                except ValueError as exc:
                    return HTTPStatus.BAD_REQUEST, {"success": False, "message": str(exc)}
            if route_path.endswith("/work"):
                sr_id = _path_int(route_path, prefix="/dispatch/sr/", suffix="/work")
                if sr_id is None:
                    return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid service request id."}
                try:
                    return HTTPStatus.OK, await container.dispatch_service.get_dispatch_sr_work_payload(sr_id=sr_id)
                except ValueError as exc:
                    return HTTPStatus.BAD_REQUEST, {"success": False, "message": str(exc)}
            if route_path.endswith("/sms_capabilities"):
                sr_id = _path_int(route_path, prefix="/dispatch/sr/", suffix="/sms_capabilities")
                if sr_id is None:
                    return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid service request id."}
                try:
                    return HTTPStatus.OK, await container.dispatch_service.get_dispatch_sr_sms_capabilities_payload(sr_id=sr_id)
                except ValueError as exc:
                    return HTTPStatus.BAD_REQUEST, {"success": False, "message": str(exc)}
            if route_path.endswith("/sms/history"):
                sr_id = _path_int(route_path, prefix="/dispatch/sr/", suffix="/sms/history")
                if sr_id is None:
                    return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid service request id."}
                try:
                    return HTTPStatus.OK, await container.dispatch_service.get_dispatch_sr_sms_history_payload(sr_id=sr_id)
                except ValueError as exc:
                    return HTTPStatus.BAD_REQUEST, {"success": False, "message": str(exc)}
            if route_path.endswith("/photo_compliance"):
                sr_id = _path_int(route_path, prefix="/dispatch/sr/", suffix="/photo_compliance")
                if sr_id is None:
                    return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid service request id."}
                try:
                    return HTTPStatus.OK, await container.dispatch_service.get_dispatch_sr_photo_compliance_payload(sr_id=sr_id)
                except ValueError as exc:
                    return HTTPStatus.BAD_REQUEST, {"success": False, "message": str(exc)}
        if method == "POST" and route_path.startswith("/dispatch/sr/"):
            if route_path.endswith("/sms/preview"):
                sr_id = _path_int(route_path, prefix="/dispatch/sr/", suffix="/sms/preview")
                if sr_id is None:
                    return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid service request id."}
                intent = str((body or {}).get("intent") or "")
                if not intent:
                    return HTTPStatus.BAD_REQUEST, {"success": False, "message": "intent is required."}
                try:
                    return HTTPStatus.OK, await container.dispatch_service.preview_dispatch_sr_sms_payload(
                        sr_id=sr_id,
                        intent=intent,
                        custom_message=str((body or {}).get("customMessage") or "") or None,
                    )
                except ValueError as exc:
                    return HTTPStatus.BAD_REQUEST, {"success": False, "message": str(exc)}
            if route_path.endswith("/sms/send"):
                sr_id = _path_int(route_path, prefix="/dispatch/sr/", suffix="/sms/send")
                if sr_id is None:
                    return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid service request id."}
                intent = str((body or {}).get("intent") or "")
                if not intent:
                    return HTTPStatus.BAD_REQUEST, {"success": False, "message": "intent is required."}
                try:
                    return HTTPStatus.OK, await container.dispatch_service.send_dispatch_sr_sms(
                        sr_id=sr_id,
                        intent=intent,
                        actor_user_id=dispatcher_user_id,
                        custom_message=str((body or {}).get("customMessage") or "") or None,
                    )
                except ValueError as exc:
                    return HTTPStatus.BAD_REQUEST, {"success": False, "message": str(exc)}

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
                    assigned_owner_bluefolder_user_id = int(payload_body.get("assignedOwnerBluefolderUserId") or 0) or None
                    assigned_owner_discord_user_id = int(payload_body.get("assignedOwnerDiscordUserId") or 0) or None
                    if assigned_owner_bluefolder_user_id is None and assigned_owner_discord_user_id is None:
                        return HTTPStatus.BAD_REQUEST, {
                            "success": False,
                            "message": "assignedOwnerBluefolderUserId must be a positive BlueFolder user id.",
                        }
                    payload = await container.dispatch_service.assign_dispatch_attention_item(
                        item_id=item_id,
                        assigned_owner_bluefolder_user_id=assigned_owner_bluefolder_user_id,
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
            try:
                payload = await container.dispatch_service.get_dispatch_route_payload(
                    technician_bluefolder_user_id=bluefolder_user_id,
                    route_date=(query.get("date") or [None])[0],
                    origin_address=(query.get("origin_address") or [None])[0],
                    destination_address=(query.get("destination_address") or [None])[0],
                    optimize=((query.get("optimize") or ["false"])[0].strip().lower() == "true"),
                )
            except ValueError as exc:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": str(exc)}
            return HTTPStatus.OK, payload

        if method == "POST" and route_path == "/dispatch/routes/simulate":
            payload_body = body or {}
            existing_stops = payload_body.get("existingStops")
            added_stops = payload_body.get("addedStops")
            removed_ids = payload_body.get("removedIds")
            manual_order = payload_body.get("manualOrder")
            if not isinstance(existing_stops, list):
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": "existingStops must be a list."}
            if added_stops is not None and not isinstance(added_stops, list):
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": "addedStops must be a list."}
            if removed_ids is not None and not isinstance(removed_ids, list):
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": "removedIds must be a list."}
            if manual_order is not None and not isinstance(manual_order, list):
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": "manualOrder must be a list."}
            payload = await container.dispatch_service.get_dispatch_route_simulation_payload(
                technician_bluefolder_user_id=payload_body.get("technicianBluefolderUserId")
                if isinstance(payload_body.get("technicianBluefolderUserId"), int)
                else None,
                existing_stops=[item for item in existing_stops if isinstance(item, dict)],
                added_stops=[item for item in (added_stops or []) if isinstance(item, dict)],
                removed_ids=[str(item) for item in (removed_ids or [])],
                manual_order=[str(item) for item in (manual_order or [])],
                route_date=str(payload_body.get("routeDate") or "").strip() or None,
                origin_address=str(payload_body.get("originAddress") or "").strip() or None,
                destination_address=str(payload_body.get("destinationAddress") or "").strip() or None,
                optimize=bool(payload_body.get("optimize")),
            )
            return HTTPStatus.OK, payload

        if method == "GET" and route_path == "/dispatch/routes/heatmap":
            try:
                payload = await container.dispatch_service.get_dispatch_heatmap_payload(
                    technician_bluefolder_user_id=_query_int(query, "bluefolder_user_id")
                )
            except ValueError as exc:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": str(exc)}
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

        if method == "POST" and route_path == "/dispatch/intake/upload":
            payload_body = body or {}
            file_name = str(payload_body.get("fileName") or "").strip()
            content_base64 = str(payload_body.get("contentBase64") or "").strip()
            if not file_name:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": "fileName is required."}
            if not content_base64:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": "contentBase64 is required."}
            try:
                spreadsheet_path = _store_uploaded_intake_file(file_name=file_name, content_base64=content_base64)
            except ValueError as exc:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": str(exc)}
            return HTTPStatus.OK, {
                "success": True,
                "message": f"Uploaded {file_name}.",
                "fileName": file_name,
                "spreadsheetPath": spreadsheet_path,
            }

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

        if method == "POST" and route_path == "/dispatch/intake/manual/preview":
            payload_body = body or {}
            if not isinstance(payload_body, dict):
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Manual intake payload must be a JSON object."}
            request_body = payload_body.get("request")
            if not isinstance(request_body, dict):
                request_body = payload_body
            try:
                return HTTPStatus.OK, container.service_smith_service.preview_manual_service_request_payload(
                    request=request_body,
                    duplicate_mode=str(payload_body.get("duplicateMode") or "error"),
                )
            except (RuntimeError, ValueError) as exc:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": str(exc)}

        if method == "POST" and route_path == "/dispatch/intake/manual/import":
            payload_body = body or {}
            if not isinstance(payload_body, dict):
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Manual intake payload must be a JSON object."}
            request_body = payload_body.get("request")
            if not isinstance(request_body, dict):
                request_body = payload_body
            try:
                return HTTPStatus.OK, container.service_smith_service.import_manual_service_request_payload(
                    request=request_body,
                    duplicate_mode=str(payload_body.get("duplicateMode") or "error"),
                    confirmed=bool(payload_body.get("confirmed")),
                    allow_validation_override=bool(payload_body.get("allowValidationOverride")),
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
        parts_user_id = _identity_actor_user_id(parts_user)
        parts_user_label = _identity_operator_label(identity=parts_user, directory=container.technician_directory_service)

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
                try:
                    return HTTPStatus.OK, await container.parts_cannon_service.get_parts_case_timeline_payload(reference=reference)
                except ValueError as exc:
                    return HTTPStatus.BAD_REQUEST, {"success": False, "message": str(exc)}
            reference = _path_tail(route_path, prefix="/parts/cases/")
            if not reference:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid parts case reference."}
            try:
                return HTTPStatus.OK, await container.parts_cannon_service.get_parts_case_payload(reference=reference)
            except ValueError as exc:
                return HTTPStatus.BAD_REQUEST, {"success": False, "message": str(exc)}

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
                requested_by_label=parts_user_label,
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
        return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Technician identity could not be resolved."}
    if isinstance(technician, tuple):
        discord_user_id = technician[0]
        bluefolder_user_id = technician[1]
        actor_label = f"Discord user {discord_user_id}"
    else:
        discord_user_id = technician.discord_user_id
        bluefolder_user_id = technician.bluefolder_user_id
        actor_label = technician.actor_label

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
    if method == "POST" and route_path.endswith("/closeout/preview"):
        sr_id = _path_int(route_path, prefix="/tech/jobs/", suffix="/closeout/preview")
        if sr_id is None:
            return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid service request id."}
        payload = await container.technician_api_service.preview_closeout(
            sr_id=sr_id,
            technician_discord_user_id=discord_user_id,
            technician_bluefolder_user_id=bluefolder_user_id,
            labor_code=str(payload_body.get("laborCode") or ""),
            work_performed=str(payload_body.get("workPerformed") or ""),
            started_at_epoch_ms=payload_body.get("startedAtEpochMs")
            if isinstance(payload_body.get("startedAtEpochMs"), int)
            else None,
            ended_at_epoch_ms=payload_body.get("endedAtEpochMs")
            if isinstance(payload_body.get("endedAtEpochMs"), int)
            else None,
            duration_minutes=payload_body.get("durationMinutes")
            if isinstance(payload_body.get("durationMinutes"), int)
            else None,
            signed_by=str(payload_body.get("signedBy") or "") or None,
            signature_png_base64=str(payload_body.get("signatureDataBase64") or "") or None,
            customer_approved=bool(payload_body.get("customerApproved")),
            final_outcome=str(payload_body.get("finalOutcome") or "completed"),
            outcome_note=str(payload_body.get("outcomeNote") or "") or None,
        )
        return HTTPStatus.OK, payload

    if method == "POST" and route_path.endswith("/closeout/submit"):
        sr_id = _path_int(route_path, prefix="/tech/jobs/", suffix="/closeout/submit")
        if sr_id is None:
            return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid service request id."}
        payload = await container.technician_api_service.submit_closeout(
            sr_id=sr_id,
            technician_discord_user_id=discord_user_id,
            technician_bluefolder_user_id=bluefolder_user_id,
            technician_actor_label=actor_label,
            labor_code=str(payload_body.get("laborCode") or ""),
            work_performed=str(payload_body.get("workPerformed") or ""),
            started_at_epoch_ms=payload_body.get("startedAtEpochMs")
            if isinstance(payload_body.get("startedAtEpochMs"), int)
            else None,
            ended_at_epoch_ms=payload_body.get("endedAtEpochMs")
            if isinstance(payload_body.get("endedAtEpochMs"), int)
            else None,
            duration_minutes=payload_body.get("durationMinutes")
            if isinstance(payload_body.get("durationMinutes"), int)
            else None,
            signed_by=str(payload_body.get("signedBy") or "") or None,
            signature_png_base64=str(payload_body.get("signatureDataBase64") or "") or None,
            customer_approved=bool(payload_body.get("customerApproved")),
            final_outcome=str(payload_body.get("finalOutcome") or "completed"),
            outcome_note=str(payload_body.get("outcomeNote") or "") or None,
        )
        return HTTPStatus.OK, payload

    if method == "POST" and route_path.endswith("/status"):
        sr_id = _path_int(route_path, prefix="/tech/jobs/", suffix="/status")
        if sr_id is None:
            return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid service request id."}
        payload = await container.technician_api_service.update_status(
            sr_id=sr_id,
            technician_discord_user_id=discord_user_id,
            technician_bluefolder_user_id=bluefolder_user_id,
            technician_actor_label=actor_label,
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
            technician_actor_label=actor_label,
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
            technician_actor_label=actor_label,
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
            technician_actor_label=actor_label,
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
            technician_actor_label=actor_label,
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
            technician_actor_label=actor_label,
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
            technician_actor_label=actor_label,
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
            technician_actor_label=actor_label,
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
            technician_actor_label=actor_label,
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

    if method == "POST" and route_path.endswith("/photos/upload"):
        sr_id = _path_int(route_path, prefix="/tech/jobs/", suffix="/photos/upload")
        if sr_id is None:
            return HTTPStatus.BAD_REQUEST, {"success": False, "message": "Invalid service request id."}
        payload = await container.technician_api_service.upload_job_photo(
            sr_id=sr_id,
            label=str(payload_body.get("label") or ""),
            filename=str(payload_body.get("filename") or ""),
            content_type=str(payload_body.get("contentType") or "") or None,
            data_base64=str(payload_body.get("dataBase64") or ""),
            technician_discord_user_id=discord_user_id,
            technician_bluefolder_user_id=bluefolder_user_id,
            technician_actor_label=actor_label,
        )
        return HTTPStatus.OK, payload

    return HTTPStatus.NOT_FOUND, {"success": False, "message": "Not found"}


def _resolve_dispatcher_identity(*, container: ServiceContainer, dispatcher_subject: str | None, dispatcher_id: str | None):
    """Resolve a dispatch or admin caller from web operator or legacy Discord context."""
    identity = _resolve_operator_identity(container=container, subject=dispatcher_id or dispatcher_subject)
    if identity is None:
        return None
    if not (identity.is_dispatcher or identity.is_admin):
        return None
    return identity


def _resolve_parts_identity(*, container: ServiceContainer, parts_subject: str | None, parts_id: str | None):
    """Resolve a parts or admin caller from web operator or legacy Discord context."""
    identity = _resolve_operator_identity(container=container, subject=parts_id or parts_subject)
    if identity is None:
        return None
    if not (identity.is_parts or identity.is_admin):
        return None
    return identity


def _resolve_operator_identity(*, container: ServiceContainer, subject: str | None):
    """Resolve a local operator id while preserving old numeric Discord-only test doubles."""
    directory = container.technician_directory_service
    if hasattr(directory, "resolve_operator_identity"):
        return directory.resolve_operator_identity(subject=subject)
    if not subject or not subject.isdigit():
        return None
    return directory.resolve_identity(user_id=int(subject), role_ids=set())


def _identity_actor_user_id(identity) -> int:
    """Return the integer actor id used by legacy audit fields."""
    return getattr(identity, "actor_user_id", None) or identity.discord_user_id


def _identity_operator_id(identity) -> str | None:
    """Return a local operator id when available."""
    return getattr(identity, "operator_id", None)


def _identity_operator_label(*, identity, directory) -> str:
    """Return a human-readable label for API-originated operator actions."""
    operator_id = _identity_operator_id(identity)
    if operator_id and operator_id != str(identity.discord_user_id or ""):
        return operator_id
    actor_user_id = _identity_actor_user_id(identity)
    if hasattr(directory, "discord_mention"):
        return directory.discord_mention(actor_user_id)
    return str(actor_user_id)


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
    value = unquote(path[len(prefix):].strip("/"))
    return value or None


def _path_action(path: str, *, prefix: str) -> tuple[str, str] | None:
    """Parse /prefix/<item_id>/<action> paths."""
    if not path.startswith(prefix):
        return None
    remainder = unquote(path[len(prefix):].strip("/"))
    if "/" not in remainder:
        return None
    item_id, action = remainder.rsplit("/", 1)
    if not item_id or not action:
        return None
    return item_id, action


def _store_uploaded_intake_file(*, file_name: str, content_base64: str) -> str:
    suffix = Path(file_name).suffix.lower()
    if suffix not in {".csv", ".xls", ".xlsx"}:
        raise ValueError("Only .csv, .xls, and .xlsx uploads are supported.")
    try:
        payload = base64.b64decode(content_base64, validate=True)
    except Exception as exc:
        raise ValueError(f"Invalid upload payload: {exc}") from exc
    temp_dir = Path(tempfile.gettempdir()) / "ops_hub_intake_uploads"
    temp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix="dispatch-intake-",
        suffix=suffix,
        dir=temp_dir,
        delete=False,
    ) as handle:
        handle.write(payload)
        return handle.name


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

            def do_HEAD(self) -> None:  # noqa: N802
                self._dispatch("HEAD")

            def do_POST(self) -> None:  # noqa: N802
                self._dispatch("POST")

            def do_DELETE(self) -> None:  # noqa: N802
                self._dispatch("DELETE")

            def do_OPTIONS(self) -> None:  # noqa: N802
                self.send_response(HTTPStatus.NO_CONTENT)
                self._send_cors_headers()
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                logger.info("Technician API " + format, *args)

            def _dispatch(self, method: str) -> None:
                started_at = time.perf_counter()
                status: HTTPStatus | None = None
                completed_status = int(HTTPStatus.INTERNAL_SERVER_ERROR)
                try:
                    if method in {"GET", "HEAD"} and self._is_landing_request():
                        self._html(HTTPStatus.OK, render_landing_page(), include_body=method != "HEAD")
                        completed_status = int(HTTPStatus.OK)
                        return
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
                    completed_status = int(status)
                except (BrokenPipeError, ConnectionResetError):
                    completed_status = 499
                    logger.info("Technician API client disconnected before response completed")
                except Exception as exc:
                    logger.exception("Technician API request failed")
                    try:
                        self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"success": False, "message": str(exc)})
                        completed_status = int(HTTPStatus.INTERNAL_SERVER_ERROR)
                    except (BrokenPipeError, ConnectionResetError):
                        completed_status = 499
                        logger.info("Technician API client disconnected while sending error response")
                finally:
                    logger.info(
                        "Technician API request completed",
                        extra={
                            "status": completed_status,
                            "duration_ms": int((time.perf_counter() - started_at) * 1000),
                            "cmd": f"{method} {self.path}",
                        },
                    )

            def _read_json(self) -> dict[str, object]:
                length = int(self.headers.get("Content-Length") or "0")
                if length <= 0:
                    return {}
                raw = self.rfile.read(length).decode("utf-8")
                return json.loads(raw) if raw.strip() else {}

            def _json(self, status: HTTPStatus, payload: object) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self._send_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _html(self, status: HTTPStatus, payload: str, *, include_body: bool = True) -> None:
                body = payload.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "public, max-age=60")
                self.end_headers()
                if include_body:
                    self.wfile.write(body)

            def _is_landing_request(self) -> bool:
                route_path = urlparse(self.path).path.rstrip("/") or "/"
                return route_path == "/"

            def _send_cors_headers(self) -> None:
                origin = self.headers.get("Origin") or "*"
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
                self.send_header(
                    "Access-Control-Allow-Headers",
                    "Accept, Authorization, Content-Type, X-Dispatch-Subject, X-Technician-Subject, X-Parts-Subject",
                )
                self.send_header("Access-Control-Max-Age", "600")
                self.send_header("Vary", "Origin")

        return Handler


def build_api_server(*, settings: Settings, container: ServiceContainer) -> TechnicianApiServer:
    """Construct the technician API server wrapper."""
    return TechnicianApiServer(settings=settings, container=container)
