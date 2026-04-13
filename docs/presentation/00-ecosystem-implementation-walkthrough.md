# OpsHub Ecosystem Implementation Walkthrough

## Purpose

This guide explains how the current OpsHub ecosystem fits into an existing BlueFolder environment without causing operational chaos.

BlueFolder remains the system of record. OpsHub is the system-of-action layer that gives each role a focused interface:

- OpsHub: backend brain, workflow state, BlueFolder access, policy, and audit layer.
- RouteDesk: dispatch board, attention queue, service request context, route planning support, and intake tooling.
- PartsDesk: parts board, cases, requests, and BlueFolder-native parts lifecycle updates.
- FieldDesk: Android technician workflow for Today, Queue, job detail, notes, photos, parts, and closeout.
- Discord: optional enhancement for commands, notifications, and mentions. It is not the required frontend identity provider.

## Current Standing

The ecosystem is presentation-capable, with a few areas still best treated as pilot/hardening scope.

Ready now:

- OpsHub runs behind the presentation Docker stack.
- `https://ops-hub.org` serves the OpsHub landing page/API.
- `https://routedesk.ops-hub.org` serves RouteDesk.
- `https://partsdesk.ops-hub.org` serves PartsDesk.
- RouteDesk and PartsDesk use per-browser OpsHub operator IDs.
- FieldDesk stores technician identity per device.
- BlueFolder API access is server-side through OpsHub.

Important boundary:

- FieldDesk and web apps should not each carry BlueFolder API credentials.
- Use one BlueFolder utility/API account on the OpsHub server.
- Attribute the actual dispatcher/parts operator/technician in OpsHub audit fields and BlueFolder note text where possible.

## Identity Model

Use these identity layers:

- OpsHub operator ID: role-facing app identity, such as `route-desk`, `parts-desk`, or `tech-mike`.
- BlueFolder user ID: BlueFolder technician/user identity used for assignment lookups and service request context.
- Discord user ID: optional linked identity for bot commands, role gating, mentions, and notifications.
- BlueFolder utility credential: one server-side credential used by OpsHub to read/write BlueFolder.

Presentation defaults currently configured locally:

- RouteDesk operator ID: `route-desk`
- PartsDesk operator ID: `parts-desk`
- FieldDesk technician ID: the tablet setting should be the correct BlueFolder technician ID or supported mapped technician subject.

## Safe BlueFolder Rollout Pattern

Use a phased rollout:

1. Read-only validation: connect OpsHub to BlueFolder and verify lookups, assignments, status catalog, and SR context.
2. Presentation mode: enable RouteDesk and PartsDesk against OpsHub, but use known-safe SRs and avoid broad live writes.
3. Controlled pilot: allow a few low-risk writes, such as parts notes or technician notes, with visible attribution text.
4. Field pilot: put FieldDesk on one or two tablets with OpsHub backend mode and a known technician ID.
5. Production cutover: expand users only after audit text, error messages, and rollback paths are clear.

## BlueFolder Write Strategy

Recommended model:

- OpsHub uses one BlueFolder utility account/API key.
- Frontends authenticate to OpsHub.
- OpsHub records who performed the action using OpsHub operator ID and, when relevant, BlueFolder technician ID.
- BlueFolder may show the technical author as the utility account unless the BlueFolder endpoint supports impersonation.
- Notes should include human attribution, such as `Submitted via FieldDesk by tech-mike / BF user 12345`.

Avoid:

- giving every technician a BlueFolder API key
- compiling BlueFolder credentials into any frontend bundle
- treating Discord ID as the required identity for web/tablet usage
- letting RouteDesk, PartsDesk, and FieldDesk write directly to BlueFolder independently

## Daily Presentation Flow

Use this sequence when demonstrating the ecosystem:

1. Open `https://ops-hub.org` and explain OpsHub as the brain.
2. Open RouteDesk and show dispatch visibility, attention items, SR context, and route support.
3. Open PartsDesk and show parts cases, request handling, and BlueFolder status context.
4. Open FieldDesk on the tablet and show Today, Queue, a job detail, note/photo path, and closeout path.
5. Explain that all products are clients of OpsHub and BlueFolder remains the record system.

## Safe Implementation Checklist

Before touching a real BlueFolder tenant:

- Confirm OpsHub can reach BlueFolder with the utility credential.
- Confirm `OPS_HUB_TECHNICIAN_API_TOKEN` is set and treated as rotatable.
- Confirm RouteDesk uses an OpsHub operator ID, not a hardcoded Discord ID.
- Confirm PartsDesk uses an OpsHub operator ID, not a hardcoded Discord ID.
- Confirm FieldDesk is in OpsHub backend mode unless explicitly testing BlueFolder-direct fallback.
- Confirm known-good SRs exist for the walkthrough.
- Confirm rollback means stopping the OpsHub presentation stack or disabling write actions, not editing every frontend.

## What Could Still Cause Chaos

Highest-risk items:

- unclear BlueFolder note authorship if utility-account writes are not clearly attributed
- broad live writes before a small pilot verifies endpoint behavior
- tablets left in direct BlueFolder mode with old credentials
- Cloudflare tunnel pointing a hostname at the wrong local service
- browser cache holding stale web assets after rebuilds
- users entering Discord IDs when an OpsHub operator ID is expected

## Operational Rule

When in doubt, keep BlueFolder as the record and OpsHub as the action/audit layer. Do not distribute BlueFolder API access to every frontend or user.
