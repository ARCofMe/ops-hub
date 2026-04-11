# OpsHub Ecosystem Release Prep

Use this before any stakeholder demo, pilot handoff, or stable release cut.

## Goal

Verify that the OpsHub ecosystem is presentation-safe:

- RouteDesk is connected and launch-ready
- PartsDesk is connected and launch-ready
- FieldDesk is configured on-device and workflow-safe
- cross-app launchers are accurate
- the field workflow can be demonstrated without dead ends

## Web Preflight

From `ops-hub`, run the local ecosystem preflight first:

```bash
.venv/bin/python -m ops_hub.ecosystem_preflight --root ..
```

Treat `FAIL` rows as release blockers and `MANUAL` rows as device checks to perform on the tablet.
Use `--strict` when cutting a release candidate so warnings and manual rows fail the command until you clear or accept them.

To make the FieldDesk tablet check machine-readable, export the debug app preferences and pass them in:

```bash
adb shell run-as com.example.arcomtechapp cat shared_prefs/arcom_prefs.xml > /tmp/fielddesk-arcom-prefs.xml
.venv/bin/python -m ops_hub.ecosystem_preflight --root .. --fielddesk-prefs /tmp/fielddesk-arcom-prefs.xml --strict
```

Do not commit the exported preferences file. It can contain API keys.

For a field-ready presentation, publish OpsHub through Cloudflare Tunnel and use the production endpoint:

```text
https://ops-hub.org
```

The Cloudflare route should point at the OpsHub technician API service, usually `http://localhost:8787` on the host running OpsHub.
Verify the tunnel before configuring the tablet:

```bash
curl https://ops-hub.org/health
```

An unauthenticated request should return `401`. An authenticated request should return:

```json
{"ok": true, "service": "ops-hub", "api": "technician"}
```

Then configure FieldDesk on the tablet for `Ops Hub` mode with base URL `https://ops-hub.org`.
Use the same technician API token configured in `OPS_HUB_TECHNICIAN_API_TOKEN`.

For a local tablet rehearsal without Cloudflare, run the API-only entrypoint:

```bash
.venv/bin/python -m ops_hub.api_main
adb reverse tcp:8787 tcp:8787
```

Then configure FieldDesk on the tablet for `Ops Hub` mode with base URL `http://127.0.0.1:8787`.

### RouteDesk

Open `Settings` and confirm:

- overall status says `Ready for presentation`
- API base is set
- dispatcher ID is set
- default technician is selected
- PartsDesk launcher is ready
- FieldDesk launcher is ready

Then confirm:

- attention board loads
- opening an SR works
- selecting an attention item can open the SR view

### PartsDesk

Open `Settings` and confirm:

- overall status says `Ready for presentation`
- RouteDesk launcher is ready
- FieldDesk launcher is ready
- case restore is enabled
- filter persistence is enabled

Then confirm:

- cases load
- requests load
- opening a case or request preserves context cleanly

## FieldDesk Preflight

On the tablet, open `Settings` and confirm:

- backend mode is correct
- server URL is correct
- API key is present
- technician ID is present
- OpsHub, RouteDesk, and PartsDesk URLs are populated if those launchers are part of the demo

Then open `Today` and confirm:

- jobs load
- the summary strip shows `Queue`, `Done`, and `Pending` counts cleanly
- the active card shows `Stop X of Y`
- the active card matches the earliest incomplete stop in service-window order
- service-window order is correct
- the active stop is not jumping to a PM stop before AM work
- `Refresh queue` reloads the list without leaving `Today`

Then open `Queue` and confirm:

- stop order matches service windows
- route launch opens cleanly
- Google Maps receives the listed stop order without re-optimizing it into the wrong sequence

Then verify workflow:

- job detail opens from `Today`
- notes can be drafted or synced
- photos can be captured
- photo attach behavior matches backend mode
- closeout path is reachable

## Demo Narrative

Use this sequence:

1. RouteDesk: dispatch, attention, SR context
2. PartsDesk: parts visibility and request handling
3. FieldDesk: next stop, job workflow, notes/photos/closeout

## Stop Conditions

Pause the demo or release cut if any of these are true:

- a sibling launcher points to the wrong environment
- FieldDesk queue order is wrong
- the expected stop does not appear first
- `Today` highlights a completed job while an incomplete stop remains
- a workflow screen opens without a selected job
- photo attach messaging does not match the active backend
- a web app title or branding label is inconsistent
