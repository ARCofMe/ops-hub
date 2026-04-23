# FieldDesk Web Wrapper Direction

## Decision

FieldDesk should move to a web-first frontend hosted inside a thin Android wrapper.

The goal is:

- one technician workflow UI
- one faster release path for field workflow changes
- Android used only where device-native behavior is actually needed

## Current repo shape

- `fielddesk-app`: mobile-first web FieldDesk over `/tech/*`
- `ARCoMTechApp`: existing Android FieldDesk implementation
- `ops-hub`: shared backend and technician API

## Boundary

The web frontend should own:

- today queue
- job detail
- timeline
- notes
- parts-needed handoff
- quote-needed handoff
- reschedule handoff
- photo-prep workflow

Android should own only:

- secure local config persistence
- authenticated web hosting
- camera capture bridge
- offline storage and deferred sync
- push notifications
- device location integration where needed

## Wrapper contract

The Android host should provide:

- stored Ops Hub API base URL
- stored technician API token
- stored technician subject
- optional native bridge object for:
  - `capturePhoto`
  - `uploadPhoto`
  - `getOfflineQueueState`
  - `enqueueOfflineAction`
  - `getDeviceLocation`
  - `openExternalNavigation`

The web app should remain usable even before those native hooks exist.

## Rollout

1. Use `fielddesk-app` as the primary workflow UI in browser.
2. Host that same UI in Android.
3. Keep the current native screens only as fallback during transition.
4. Move one native workflow at a time behind the web client.

## Engineering rule

Do not split technician workflow logic across two separate primary UIs long term.

The backend contract should stay in Ops Hub, and the technician workflow presentation should converge on the web client.
