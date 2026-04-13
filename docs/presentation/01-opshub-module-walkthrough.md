# OpsHub Module Walkthrough

## Role

OpsHub is the brain of the ecosystem. It centralizes BlueFolder access, workflow state, API authentication, policy checks, and operator-facing route endpoints.

OpsHub is not intended to replace BlueFolder. It coordinates work around BlueFolder.

## What OpsHub Owns

- BlueFolder API credential handling.
- Technician API and web API endpoints.
- Workflow state files and audit events.
- Dispatch attention derivation.
- Parts board/case/request APIs.
- FieldDesk job, note, photo, parts, and closeout APIs.
- Public landing page at `https://ops-hub.org`.
- Optional Discord commands and notifications.

## What BlueFolder Still Owns

- service request records
- customer/job facts
- assignment source data
- service request notes
- parts lifecycle comments when written back
- labor/closeout record where supported

## Runtime Shape

Presentation Docker stack:

- `ops-hub`: backend/API on local port `8787`
- `routedesk`: RouteDesk frontend on local port `4175`
- `partsdesk`: PartsDesk frontend on local port `4176`

Public routes:

- `https://ops-hub.org` -> OpsHub
- `https://routedesk.ops-hub.org` -> RouteDesk
- `https://partsdesk.ops-hub.org` -> PartsDesk

## Key Settings

Server-side:

- `OPS_HUB_TECHNICIAN_API_TOKEN`: shared API bearer token for frontend/API calls.
- `OPS_HUB_BLUEFOLDER_API_KEY`: BlueFolder utility/API credential.
- `OPS_HUB_BLUEFOLDER_ACCOUNT_NAME` or `OPS_HUB_BLUEFOLDER_BASE_URL`: BlueFolder tenant target.
- `OPS_HUB_DISPATCHER_OPERATOR_IDS`: RouteDesk operator allowlist.
- `OPS_HUB_PARTS_OPERATOR_IDS`: PartsDesk operator allowlist.
- `OPS_HUB_TECHNICIAN_BLUEFOLDER_USER_MAP`: optional Discord-to-BlueFolder technician linkage.

Local presentation operator IDs:

- RouteDesk: `route-desk`
- PartsDesk: `parts-desk`

## Health Checks

Expected unauthenticated behavior:

- `GET https://ops-hub.org/` returns the landing page.
- `GET https://ops-hub.org/health` returns `401` without a bearer token.

Expected authenticated behavior:

- `GET /health` returns service health.
- `GET /dispatch/board` with `X-Dispatch-Subject: route-desk` returns `200`.
- `GET /parts/board` with `X-Parts-Subject: parts-desk` returns `200`.

## How To Explain It

Use this wording:

OpsHub is the operations brain. It keeps BlueFolder as the record system, but provides role-native clients for dispatch, parts, and field teams. It prevents the frontends from needing direct BlueFolder API keys and gives us one place to enforce workflow, audit, routing, and policy.

## Safe Rollout Steps

1. Start OpsHub against a known BlueFolder tenant using a utility/API account.
2. Verify health and BlueFolder status/catalog calls.
3. Verify RouteDesk and PartsDesk operator IDs.
4. Verify one known SR through RouteDesk and PartsDesk.
5. Configure one FieldDesk tablet in OpsHub mode.
6. Keep direct BlueFolder mode only as fallback during pilot.

## Common Failure Modes

- `401`: API token missing or wrong.
- `403`: operator ID missing or not in the OpsHub allowlist.
- `502` or bad gateway: tunnel or local port is pointing at the wrong service.
- landing page works but app API fails: frontend identity/token problem, not necessarily Cloudflare.
- BlueFolder data missing: verify utility credential, tenant target, and known SR validity.

## Presentation Checklist

- OpsHub landing page loads.
- API stack is running.
- Docker containers are healthy.
- RouteDesk operator ID works.
- PartsDesk operator ID works.
- FieldDesk points to OpsHub, not direct BlueFolder, unless intentionally testing fallback.
