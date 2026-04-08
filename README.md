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

- Discord and role access
- technician API host/token settings
- BlueFolder credentials and connection settings
- workflow, notification, and store-file paths
- optional parts handoff integration
- optional photo archive/mailbox integration
- optional ServiceSmith intake profile storage
- optional SMS provider settings

For the supported variables and inline examples, use:

- `.env.example`

## Local Run

Create a virtual environment, install the package, then start Ops Hub:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
PYTHONPATH=src python -m ops_hub
```

## Notes

- The dispatch board and attention queue now render from the latest workflow snapshot first, then refresh in the background.
- Parts cases are no longer limited only to the currently scanned assignment set; tenant-wide parts-active SRs can surface as cases too.
- Dispatch attention ownership is BlueFolder-first. Discord owner ids remain compatibility input, not the preferred model.
- The default SMS provider mode is `dry_run`, which records preview and send attempts without sending real texts.
- Technician completed-closeout flows can now compile work summary, elapsed time, labor type, and customer signoff acknowledgement into a BlueFolder labor submission path.
