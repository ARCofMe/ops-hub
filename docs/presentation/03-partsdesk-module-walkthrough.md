# PartsDesk Module Walkthrough

## Role

PartsDesk is the parts operations frontend. It gives parts staff a focused board for parts cases, requests, and BlueFolder-backed parts lifecycle updates.

PartsDesk talks to OpsHub. OpsHub talks to BlueFolder.

## Primary Jobs

- show parts board status
- load parts cases and requests
- show BlueFolder SR status context
- support request claim/status flows
- support BlueFolder-native parts lifecycle updates
- link to RouteDesk and FieldDesk when useful

## Identity

PartsDesk should use an OpsHub operator ID.

Current presentation value:

```text
parts-desk
```

This goes in PartsDesk Settings under `OpsHub operator ID`.

Legacy linked Discord IDs still work, but Discord is not required for a parts operator to use PartsDesk.

## Screen Walkthrough

1. Open `https://partsdesk.ops-hub.org`.
2. Open Settings first.
3. Confirm API base points at `https://ops-hub.org`.
4. Confirm OpsHub operator ID is set to a parts/admin operator, such as `parts-desk`.
5. Confirm ecosystem launchers point at OpsHub, RouteDesk, and FieldDesk.
6. Return to the board.
7. Load cases and requests.
8. Open one case and explain its BlueFolder status context.

## What To Demonstrate

Board:

- Explain open parts workload and high-risk case counts.
- Show that the board is role-specific and not a generic BlueFolder clone.

Cases:

- Open a case.
- Show service request reference, stage, age, parts context, and BlueFolder SR status.
- Explain whether the case is active parts work or blocked by quote/customer/closed SR status.

Requests:

- Show supplemental tracked requests if enabled.
- Explain that request tracking helps operations, but BlueFolder remains the record.

BlueFolder-native lifecycle:

- Ordered, ETA, tracking, received, and ready updates should be routed through OpsHub.
- Use known safe SRs when demonstrating live writes.

## How PartsDesk Writes

PartsDesk writes should go through OpsHub:

- request claim/unclaim/status
- parts request sync/reconcile when enabled
- BlueFolder parts note/update routes for ordered/ETA/tracking/received/ready

PartsDesk should not hold BlueFolder API credentials.

## BlueFolder Safety

For a real tenant rollout:

- start by reading cases and requests
- verify a known SR status in BlueFolder before writing updates
- perform one controlled parts note/update with clear attribution
- avoid bulk behavior until the team agrees on how utility-account authorship appears in BlueFolder

## Common Errors

- `Could not reach OpsHub`: API base URL or tunnel problem.
- `Check the OpsHub API token`: frontend token problem.
- `Check the OpsHub parts/admin operator allowlist`: missing or invalid operator ID.
- cases empty: verify BlueFolder data, parts workflow state, and request sync assumptions.

## Presentation Script

PartsDesk is the parts desk's operating layer. It keeps BlueFolder as the official record but gives the parts team a cleaner view of cases, request history, SR status, and parts lifecycle actions. The operator identity is an OpsHub ID, not a Discord requirement.

## Preflight

- browser hard refreshed after rebuild
- Settings operator ID set
- API base correct
- cases load
- requests load
- known SR ready for safe parts update demonstration
