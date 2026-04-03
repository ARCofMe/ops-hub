# Frontend Architecture

This document defines the frontend direction for Ops Hub.

The goal is not to build three disconnected wrappers. The goal is one workflow platform with role-native clients.

## Product Shape

Keep one backend:

- BlueFolder remains the system of record
- Ops Hub owns workflow state, next actions, policy, queue logic, and audit history
- every frontend consumes the same Ops Hub domain objects

Build three role-native clients on top of that backend:

1. technician app
2. dispatch app
3. parts app

Discord remains useful as a control and notification layer, but it should stop being the primary UI for dense operational work.

## Shared Domain Contract

Every frontend should use the same core backend concepts:

- `attention_item`
- `parts_case`
- `service_request_timeline`
- job detail
- customer/contact detail
- workflow actions:
  - acknowledge
  - snooze
  - unsnooze
  - reopen
  - assign owner
  - clear owner

Do not let each frontend invent its own local state model for workflow. That creates three inconsistent products.

## API Surface

The existing technician API already gives Ops Hub a useful starting point:

- `GET /health`
- `GET /tech/me/today`
- `GET /tech/jobs`
- `GET /tech/jobs/{sr_id}`
- `GET /tech/jobs/{sr_id}/photos`
- `GET /tech/jobs/{sr_id}/parts`
- `GET /tech/jobs/{sr_id}/timeline`
- `POST /tech/jobs/{sr_id}/call_ahead`
- `POST /tech/jobs/{sr_id}/status`
- `POST /tech/jobs/{sr_id}/notes`
- `POST /tech/jobs/{sr_id}/parts`
- `POST /tech/jobs/{sr_id}/quote_needed`
- `POST /tech/jobs/{sr_id}/reschedule`
- `POST /tech/jobs/{sr_id}/photo_compliance`
- `POST /tech/jobs/{sr_id}/photos/prepare`

These routes are implemented in [`src/ops_hub/api_server.py`](../src/ops_hub/api_server.py).

### Technician App API MVP

The next technician API expansion after the current routes should focus on richer photo upload and structured job-close flows, not on queue-control actions.

The technician app should not need queue-control actions like assign owner or snooze.

### Dispatch App API MVP

Dispatch-facing endpoints that expose workflow state directly:

- `GET /dispatch/board`
- `GET /dispatch/attention`
- `GET /dispatch/attention/{item_id}`
- `GET /dispatch/sr/{sr_id}/timeline`
- `GET /dispatch/sr/{sr_id}/customer`
- `GET /dispatch/sr/{sr_id}/work`
- `GET /dispatch/routes/preview`
- `GET /dispatch/routes/heatmap`
- `GET /dispatch/intake/formats`
- `GET /dispatch/intake/profiles`
- `POST /dispatch/intake/analyze`
- `POST /dispatch/intake/preview`
- `POST /dispatch/intake/import`
- `POST /dispatch/intake/profiles`
- `DELETE /dispatch/intake/profiles/{name}`
- `POST /dispatch/attention/bulk`
- `POST /dispatch/attention/{item_id}/ack`
- `POST /dispatch/attention/{item_id}/snooze`
- `POST /dispatch/attention/{item_id}/unsnooze`
- `POST /dispatch/attention/{item_id}/reopen`
- `POST /dispatch/attention/{item_id}/assign`
- `POST /dispatch/attention/{item_id}/clear_owner`

Useful query filters:

- `stage`
- `age`
- `owner_discord_user_id`
- `bluefolder_user_id`
- `status`
- `reference`

Current route-planning support:

- route preview can be loaded per technician with optional `origin_address` and `destination_address`
- route preview also supports `optimize=true` when dispatch wants the legacy routing backend to return a better stop order
- assignment heatmaps can be loaded team-wide or for one technician
- schedule writeback is still a later phase

The next dispatch API expansion after the current routes should add route-planning and schedule-writeback endpoints when the dispatch web starts absorbing more of the old route planner.

### Parts App API MVP

Add parts-facing endpoints around `parts_case` instead of raw request rows:

- `GET /parts/board`
- `GET /parts/cases`
- `GET /parts/cases/{reference}`
- `GET /parts/cases/{reference}/timeline`
- `GET /parts/requests`
- `GET /parts/requests/{request_id}`
- `POST /parts/requests/{request_id}/claim`
- `POST /parts/requests/{request_id}/unclaim`
- `POST /parts/requests/{request_id}/status`
- `POST /parts/requests/sync`
- `POST /parts/requests/reconcile`
- `POST /parts/sr/{sr_id}/ordered`
- `POST /parts/sr/{sr_id}/eta`
- `POST /parts/sr/{sr_id}/tracking`
- `POST /parts/sr/{sr_id}/received`
- `POST /parts/sr/{sr_id}/ready`

Useful query filters:

- `stage`
- `age`
- `assigned_parts_user_id`
- `reference`
- `status`

Current parts-app support is split intentionally:

- `parts_case` routes give the board and case detail that the app should center on
- tracked-request routes expose the supplemental internal queue
- BlueFolder-native parts lifecycle writes are available as `/parts/sr/{sr_id}/...` routes so the app can update the real system of record without going through Discord

The next parts API expansion after the current routes should add direct case-level mutation endpoints if the app needs them. Right now the clean write path is still service-request based because BlueFolder is the system of record for ordered/ETA/tracking/received/ready updates.

## Existing Projects

### Technician App

There is already a native Android project in `ARCoMTechApp`.

Important observations:

- it already has an Ops Hub repository in `ARCoMTechApp/app/src/main/java/com/example/arcomtechapp/data/repo/OpsHubFieldOpsRepository.kt`
- it already has a backend seam in `ARCoMTechApp/app/src/main/java/com/example/arcomtechapp/data/repo/RepositoryProvider.kt`
- it still supports direct BlueFolder mode
- it already has technician-oriented workflow logic in `ARCoMTechApp/app/src/main/java/com/example/arcomtechapp/workflow/JobWorkflow.kt`

That means the tech app should evolve by deepening the Ops Hub path, not by treating BlueFolder-direct as the long-term primary mode.

Recommended direction:

- keep the Android app
- make Ops Hub the default backend mode
- move field workflow logic toward Ops Hub-native concepts like parts case, quote-needed handoff, timeline, and photo compliance
- keep BlueFolder-direct only as fallback or migration mode

### Dispatch App

There is an existing route-planning app in `dispatcher-routing-app`.

That app is still useful, but it should become a dispatch module, not the whole dispatch product.

Recommended direction:

- keep the route-planning experience as one tab or module
- add workflow board, attention queue, and SR detail around it
- do not make dispatch live in a route screen alone

### Parts App

There is no dedicated parts app yet.

That is fine. Parts should be built after dispatch, because the backend workflow layer is already closer to supporting a parts board than a technician rewrite.

## Role MVPs

### Technician App MVP

Primary jobs:

- see today’s work clearly
- call ahead quickly
- navigate without extra taps
- update status in structured form
- capture notes, parts-needed, and quote-needed handoffs
- see photo requirements and job history

Core screens:

- `My Day`
- `Job Detail`
- `Customer`
- `Timeline`
- `Photos`
- `Need Part / Need Quote`

Design constraints:

- mobile-first
- fast in poor signal conditions
- minimal typing
- large primary actions
- camera and phone actions close to the top

### Dispatch App MVP

Primary jobs:

- see queue state now
- know what is urgent, aging, or unowned
- drive scheduling from parts and quote readiness
- inspect SR history without reading comment soup
- own and resolve handoffs

Core screens:

- `Dispatch Board`
- `Attention Queue`
- `Quote Needed`
- `Ready To Schedule`
- `Owner Gaps`
- `SR Detail`
- `Timeline / History`
- `Route Planning`

Design constraints:

- dense information layout
- fast filtering
- multi-column views on desktop
- visible owner/status/age at a glance

### Parts App MVP

Primary jobs:

- work open parts cases
- record ordering, ETA, tracking, and receipt
- make the handoff to dispatch visible when a case is ready
- avoid comment-only state

Core screens:

- `Open Cases`
- `Ordered / Waiting ETA`
- `Tracking / Waiting Arrival`
- `Received`
- `Ready To Schedule`
- `Case Detail`
- `Timeline`

Design constraints:

- case-first workflow
- one SR can be resolved without opening multiple unrelated records
- blockers and next actions need to be visible immediately

## Delivery Order

Recommended order:

1. continue the current technician app
2. build the dispatch web app
3. build the parts web app

Why:

- the tech app already exists and already speaks to Ops Hub
- dispatch gets the biggest productivity jump from leaving Discord for a dense board UI
- parts can continue from Discord slightly longer than dispatch can

## 90-Day Frontend Plan

### Phase A: Stabilize The Technician App

- make Ops Hub the preferred backend
- align the current job list and detail flows to Ops Hub job/timeline/parts routes
- add explicit call-ahead, photo, and handoff actions
- validate the field workflow with live technicians

### Phase B: Build Dispatch Web

- create a workflow-first board over `attention_item`
- add owner, age, and queue-state filters
- add SR detail and timeline panel
- embed or link route-planning as a secondary workspace

### Phase C: Build Parts Web

- create a case-first parts board over `parts_case`
- add claim and lifecycle actions
- add dispatch handoff visibility when cases become scheduling-ready

## Practical Rules

- technician UI should optimize for execution
- dispatch UI should optimize for triage and control
- parts UI should optimize for state progression and handoff
- none of the frontends should duplicate BlueFolder’s raw record screens unless strictly necessary
- all frontend state should map back to Ops Hub workflow objects and events
