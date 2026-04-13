# FieldDesk Module Walkthrough

## Role

FieldDesk is the Android technician app. It should help the technician work the day in the correct order, capture useful job updates, and reduce friction in the field.

FieldDesk should prefer OpsHub backend mode. Direct BlueFolder mode is fallback/migration mode, not the long-term primary path.

## Primary Jobs

- show today's assigned jobs
- highlight the next incomplete stop
- sort queue by service windows
- open job detail quickly
- support call-ahead, notes, parts, quote-needed, photos, and closeout
- send updates through OpsHub so tablets do not need BlueFolder API credentials

## Identity

FieldDesk identity is per device in Android Settings.

Recommended model:

- backend mode: `Ops Hub`
- server URL: `https://ops-hub.org`
- API key: OpsHub technician API token
- technician ID: BlueFolder technician ID or a supported mapped technician subject

Do not give every technician a BlueFolder API key unless intentionally using direct BlueFolder fallback mode.

## Screen Walkthrough

Settings:

1. Open FieldDesk Settings.
2. Select backend mode `Ops Hub`.
3. Set server URL to `https://ops-hub.org`.
4. Set API key.
5. Set technician ID.
6. Confirm RouteDesk/PartsDesk/OpsHub URLs are populated if using launchers.

Today:

1. Open Today.
2. Confirm jobs load.
3. Confirm `Queue`, `Done`, and `Pending` counts display cleanly.
4. Confirm active card says `Stop X of Y`.
5. Confirm the first active stop is the earliest incomplete stop by service window.
6. Confirm it does not jump to a PM stop before AM work.

Queue:

1. Open Queue.
2. Confirm service-window order.
3. Confirm route launch preserves the listed stop order.
4. Do not let an external route tool reorder stops unexpectedly during a demo.

Job detail:

1. Open a job from Today or Queue.
2. Review customer/job information.
3. Test note draft/sync behavior.
4. Test photo attach behavior for the active backend mode.
5. Confirm closeout path is reachable.

## How FieldDesk Writes

FieldDesk writes should go through OpsHub:

- notes
- status updates
- parts-needed handoff
- quote-needed handoff
- photo preparation/compliance actions
- closeout/labor/signoff workflow where enabled

OpsHub then writes to BlueFolder with the utility/API credential and includes technician attribution.

## BlueFolder Safety

For a real tenant rollout:

- pilot one technician/tablet first
- verify Today ordering against BlueFolder assignments
- perform one note on a safe SR
- verify the BlueFolder note attribution is acceptable
- verify photos and closeout behavior before live production use
- keep direct BlueFolder mode available only as fallback during pilot

## Common Errors

- Today loads wrong stop first: check service-window sorting and incomplete-stop selection.
- no jobs: check technician ID and BlueFolder assignments.
- API auth failure: check OpsHub URL and API token.
- photo attach only shows a generic message: confirm backend mode and photo endpoint readiness.
- Settings back arrow returns to Settings: verify navigation state and activity stack behavior in the app build.

## Presentation Script

FieldDesk is the technician's field surface. It should answer "what is my next stop, what do I need to know, and how do I update the job?" The tablet talks to OpsHub, and OpsHub handles the BlueFolder credential centrally. That keeps field devices safer and makes rollout easier.

## Preflight

- tablet connected
- backend mode set to OpsHub
- server URL set to `https://ops-hub.org`
- technician ID set
- Today loads
- first active stop is correct
- Queue order matches service windows
- job detail opens
- notes/photos/closeout path behavior understood before demo
