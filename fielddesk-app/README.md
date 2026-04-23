# FieldDesk Web

`fielddesk-app` is the web-first FieldDesk client for Ops Hub.

It is meant to become the primary technician UI surface, with Android acting as a thin wrapper and native bridge where device integration is required.

## Current shape

- mobile-first technician queue
- active job detail
- field actions over the existing `/tech/*` Ops Hub API
- persisted wrapper-ready config:
  - API base
  - technician API token
  - technician subject
  - theme

## Commands

```bash
npm install
npm run dev
npm test
npm run build
```

## Required config

The app needs:

- Ops Hub technician API base URL
- Ops Hub technician API token
- technician subject, for example `bf:12345`

These are stored locally in the web client today. An Android wrapper should persist the same values and inject them into the hosted FieldDesk frontend.

## Near-term Android direction

The existing native Android app should move toward:

1. hosting this web client
2. persisting config locally
3. adding bridge hooks only where native device APIs are needed:
   - camera
   - offline cache
   - push notifications
   - background location

## Not finished yet

- closeout preview/submit UI
- direct camera/photo upload bridge
- offline queue and sync
- push notification bridge
- stronger technician identity bootstrap
