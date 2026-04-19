# Ops Hub

Ops Hub is the shared operations backend for ARCoM.

It sits between BlueFolder and the operator-facing products:

- `RouteDesk` for dispatch and triage
- `PartsDesk` for parts workflow
- `FieldDesk` for technicians in the field
- Discord commands for lightweight lookup, updates, and notifications

BlueFolder remains the main business record. Ops Hub adds workflow state,
queueing, next-action logic, cross-role views, and API surfaces for the apps.

## What Ops Hub Covers

- BlueFolder service request and assignment lookups
- dispatch board, triage, attention, SR detail, routing, and intake APIs
- parts board, case, request, and BlueFolder-native parts update APIs
- technician mobile APIs for job, workflow, and photo flows
- technician closeout preview/submission APIs for BlueFolder labor-backed field completion
- workflow-state ownership for attention queues, parts cases, policy events, and history
- normalized BlueFolder status semantics for frontend clients
- optional Discord commands and notifications

## Main Product Surfaces

- `RouteDesk`
  Dispatch board, triage queue, attention queue, SR workspace, routes, and intake.
- `PartsDesk`
  Parts board, case workflow, tracked requests, and dispatch handoff.
- `FieldDesk`
  Technician workflow app for jobs, notes, photos, and field updates.
- `Discord`
  Useful for fast command access, notifications, and ad hoc operational actions, but no longer the center of the product.

## Identity Model

Ops Hub is BlueFolder-first.

- BlueFolder users are first-class operational identities.
- OpsHub operator IDs are first-class web/tablet identities for RouteDesk and PartsDesk.
- Discord linkage is optional enrichment for mentions, role gating, and notification routing.
- Dispatch, technician, parts, and admin workflows should continue to work even when a user does not have a Discord account.

## Documentation

Operator guides:

- `docs/user-guide.md`
- `docs/technician-guide.md`
- `docs/dispatch-guide.md`
- `docs/parts-guide.md`
- `docs/admin-guide.md`
- `docs/workflow-guide.md`

Operational and architecture docs:

- `docs/cutover-checklist.md`
- `docs/release-prep.md`
- `docs/troubleshooting.md`
- `docs/frontend-architecture.md`
- `docs/roadmap.md`
- `docs/dispatch-sms-adapters.md`

Discord reference:

- `docs/discord-command-reference.md`

## API Surface

Current app-facing routes include:

- `GET /bluefolder/status_catalog`
- `GET /dispatch/board`
- `GET /dispatch/attention`
- `GET /dispatch/attention/<item_id>`
- `POST /dispatch/attention/<item_id>/ack`
- `POST /dispatch/attention/<item_id>/snooze`
- `POST /dispatch/attention/<item_id>/unsnooze`
- `POST /dispatch/attention/<item_id>/reopen`
- `POST /dispatch/attention/<item_id>/assign`
- `POST /dispatch/attention/<item_id>/clear_owner`
- `GET /dispatch/sr/<sr_id>/customer`
- `GET /dispatch/sr/<sr_id>/timeline`
- `GET /dispatch/sr/<sr_id>/work`
- `GET /dispatch/sr/<sr_id>/photo_compliance`
- `GET /dispatch/sr/<sr_id>/complaint_intelligence`
- `GET /dispatch/sr/<sr_id>/sms_capabilities`
- `GET /dispatch/sr/<sr_id>/sms/history`
- `POST /dispatch/sr/<sr_id>/sms/preview`
- `POST /dispatch/sr/<sr_id>/sms/send`
- `GET /dispatch/routes/preview`
- `POST /dispatch/routes/simulate`
- `GET /dispatch/routes/heatmap`
- `GET /dispatch/intake/formats`
- `GET /dispatch/intake/profiles`
- `POST /dispatch/intake/profiles`
- `POST /dispatch/intake/upload`
- `POST /dispatch/intake/analyze`
- `POST /dispatch/intake/preview`
- `POST /dispatch/intake/import`
- `GET /parts/board`
- `GET /parts/cases`
- `GET /parts/cases/<reference>`
- `GET /parts/cases/<reference>/timeline`
- `GET /parts/sr/<sr_id>/recommendation_conversation`
- `GET /parts/requests`
- `GET /parts/requests/<request_id>`
- `POST /parts/requests/<request_id>/claim`
- `POST /parts/requests/<request_id>/unclaim`
- `POST /parts/requests/<request_id>/status`
- `POST /parts/requests/sync`
- `POST /parts/requests/reconcile`
- `POST /parts/sr/<sr_id>/ordered`
- `POST /parts/sr/<sr_id>/eta`
- `POST /parts/sr/<sr_id>/tracking`
- `POST /parts/sr/<sr_id>/received`
- `POST /parts/sr/<sr_id>/ready`
- `POST /tech/jobs/<sr_id>/closeout/preview`
- `POST /tech/jobs/<sr_id>/closeout/submit`

## Configuration

Ops Hub uses environment variables through `.env`.

The main groups are:

- OpsHub operator IDs plus optional Discord and role access
- technician API host/token settings
- BlueFolder credentials and connection settings
- workflow, notification, and store-file paths
- optional parts handoff integration
- optional photo archive/mailbox integration
- optional ServiceSmith intake profile storage
- optional Complaint Intelligence SQLite integration for RouteDesk triage evidence
- optional SMS provider settings

For the supported variables and inline examples, use:

- `.env.example`

Repository-backed config files:

- `config/operator_roles.json`
- `config/technician_closeout_matrix.json`

Complaint Intelligence can be wired in read-only mode after the standalone
collector has built its SQLite database:

```bash
OPS_HUB_COMPLAINT_INTELLIGENCE_PROJECT_PATH=../complaint-intelligence
OPS_HUB_COMPLAINT_INTELLIGENCE_DATABASE_URL=sqlite:///../complaint-intelligence/complaint_intelligence.db
```

The RouteDesk-facing backend endpoint is
`GET /dispatch/sr/<sr_id>/complaint_intelligence`. It returns the normalized
complaint record, complaint tags, billed items, similar historical requests,
part recommendations, and common resolution notes when the SR exists in the
Complaint Intelligence database.

## Local Run

Create a virtual environment, install the package, then start Ops Hub:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
PYTHONPATH=src python -m ops_hub
```

## Presentation Docker Run

Ops Hub can run with RouteDesk and PartsDesk through the presentation compose file:

```bash
docker compose -f docker-compose.presentation.yml up -d --build
```

This starts:

- `ops-hub` on `http://localhost:8787`
- `routedesk` on `http://localhost:4175`
- `partsdesk` on `http://localhost:4176`

The compose file keeps Ops Hub state in the `opshub-data` Docker volume and mounts `../bluefolder-api` into the container at `/workspace/bluefolder-api`.
If you enable Cloudflare Tunnel inside the compose stack, set `CLOUDFLARED_TOKEN` in the local environment and run:

```bash
docker compose -f docker-compose.presentation.yml --profile tunnel up -d --build
```

In Cloudflare, point the public hostnames at the compose service names:

- `ops-hub.org` -> `http://ops-hub:8787`
- `routedesk.ops-hub.org` -> `http://routedesk:80`
- `partsdesk.ops-hub.org` -> `http://partsdesk:80`

Protect the frontend hostnames with Cloudflare Access or a similarly gated route before using them outside a controlled demo.
The Vite frontend bundles include the presentation API token at build time, so that token must be treated as browser-visible and rotatable.
RouteDesk dispatcher identity is not baked into the shared presentation bundle; each dispatcher sets their own ID in RouteDesk `Settings`, and the browser stores it locally.
PartsDesk parts identity follows the same model; each parts operator sets their own ID in PartsDesk `Settings`, and the browser stores it locally.
FieldDesk technician identity is per device in the Android Settings screen.

If `cloudflared` is still installed directly on the host instead of inside compose, keep the Cloudflare services pointed at:

- `http://localhost:8787`
- `http://localhost:4175`
- `http://localhost:4176`

## Notes

- The dispatch board and attention queue now render from the latest workflow snapshot first, then refresh in the background.
- Parts cases are no longer limited only to the currently scanned assignment set; tenant-wide parts-active SRs can surface as cases too.
- Dispatch attention ownership is BlueFolder-first. Discord owner ids remain compatibility input, not the preferred model.
- The default SMS provider mode is `dry_run`, which records preview and send attempts without sending real texts.
- Technician completed-closeout flows can now compile work summary, elapsed time, labor type, and customer signoff acknowledgement into a BlueFolder labor submission path.
- The default technician closeout billing matrix now lives in `config/technician_closeout_matrix.json` so warranty, OOW hourly, diagnostic-fee, and declined-repair labor can be tuned without changing app code.
