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

These routes are implemented in [api_server.py](/home/ner0tic/Documents/Projects/ARCoM/ops-hub/src/ops_hub/api_server.py).

### Technician App API MVP

The next technician API expansion after the current routes should focus on richer photo upload and structured job-close flows, not on queue-control actions.

The technician app should not need queue-control actions like assign owner or snooze.

### Dispatch App API MVP

Dispatch-facing endpoints that expose workflow state directly:

- `GET /dispatch/board`
- `GET /dispatch/attention`
- `GET /dispatch/attention/{item_id}`
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

The next dispatch API expansion after the current routes should add:

- `GET /dispatch/sr/{sr_id}/timeline`
- `GET /dispatch/sr/{sr_id}/customer`
- route-planning and schedule-writeback endpoints when the dispatch web starts absorbing more of the old route planner

### Parts App API MVP

Add parts-facing endpoints around `parts_case` instead of raw request rows:

- `GET /parts/cases`
- `GET /parts/cases/{reference}`
- `POST /parts/cases/{reference}/claim`
- `POST /parts/cases/{reference}/ordered`
- `POST /parts/cases/{reference}/eta`
- `POST /parts/cases/{reference}/tracking`
- `POST /parts/cases/{reference}/received`
- `POST /parts/cases/{reference}/ready`
- `GET /parts/cases/{reference}/timeline`

Useful query filters:

- `stage`
- `age`
- `assigned_parts_user_id`
- `reference`
- `status`

## Existing Projects

### Technician App

There is already a native Android project in [ARCoMTechApp](/home/ner0tic/Documents/Projects/ARCoM/ARCoMTechApp).

Important observations:

- it already has an Ops Hub repository in [OpsHubFieldOpsRepository.kt](/home/ner0tic/Documents/Projects/ARCoM/ARCoMTechApp/app/src/main/java/com/example/arcomtechapp/data/repo/OpsHubFieldOpsRepository.kt)
- it already has a backend seam in [RepositoryProvider.kt](/home/ner0tic/Documents/Projects/ARCoM/ARCoMTechApp/app/src/main/java/com/example/arcomtechapp/data/repo/RepositoryProvider.kt)
- it still supports direct BlueFolder mode
- it already has technician-oriented workflow logic in [JobWorkflow.kt](/home/ner0tic/Documents/Projects/ARCoM/ARCoMTechApp/app/src/main/java/com/example/arcomtechapp/workflow/JobWorkflow.kt)

That means the tech app should evolve by deepening the Ops Hub path, not by treating BlueFolder-direct as the long-term primary mode.

Recommended direction:

- keep the Android app
- make Ops Hub the default backend mode
- move field workflow logic toward Ops Hub-native concepts like parts case, quote-needed handoff, timeline, and photo compliance
- keep BlueFolder-direct only as fallback or migration mode

### Dispatch App

There is an existing route-planning app in [dispatcher-routing-app](/home/ner0tic/Documents/Projects/ARCoM/dispatcher-routing-app).

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
