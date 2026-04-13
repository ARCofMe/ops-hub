# RouteDesk Module Walkthrough

## Role

RouteDesk is the dispatch frontend. It should make dispatch decisions faster without forcing the dispatcher to live inside BlueFolder raw screens or Discord commands.

RouteDesk talks to OpsHub. OpsHub talks to BlueFolder.

## Primary Jobs

- show dispatch board health
- show attention items that need action
- open service request context
- support route planning and stop order review
- support intake/import profile work
- link out to PartsDesk and FieldDesk when useful

## Identity

RouteDesk should use an OpsHub operator ID.

Current presentation value:

```text
route-desk
```

This goes in RouteDesk Settings under `OpsHub operator ID`.

Legacy linked Discord IDs still work, but Discord is not required for a dispatcher to use RouteDesk.

## Screen Walkthrough

1. Open `https://routedesk.ops-hub.org`.
2. Open Settings first.
3. Confirm API base points at `https://ops-hub.org`.
4. Confirm OpsHub operator ID is set to a dispatch/admin operator, such as `route-desk`.
5. Confirm ecosystem launchers point at OpsHub, PartsDesk, and FieldDesk.
6. Return to the board.
7. Confirm attention board and SR detail load without `401` or `403`.

## What To Demonstrate

Dispatch board:

- Explain this is dispatch's working cockpit.
- Point out that the data comes through OpsHub, not direct BlueFolder frontend access.

Attention queue:

- Open an item.
- Explain why it needs dispatch attention.
- Show acknowledgement/snooze/owner flows only if using a known safe item.

Service request context:

- Open a known SR.
- Show customer/work/timeline/photo compliance context.
- Explain that dispatch can understand the job without jumping across tools.

Route support:

- Use the route preview or route simulation only with known data.
- Confirm stops are in service-window order before sending to a route tool.

## How RouteDesk Writes

RouteDesk writes should go through OpsHub:

- dispatch attention actions
- owner assignment
- triage disposition
- SMS preview/send where configured
- intake profile updates

RouteDesk should not hold BlueFolder API credentials.

## BlueFolder Safety

For a real tenant rollout:

- start read-only by showing board, attention, SR context, and route preview
- do not bulk-acknowledge live items during early demos
- use known-good SRs for SMS/triage/owner flows
- verify any write appears with clear attribution in OpsHub and/or BlueFolder notes

## Common Errors

- `Could not reach OpsHub`: API base URL or tunnel problem.
- `Check the OpsHub API token`: frontend token problem.
- `Check the OpsHub dispatcher/admin operator allowlist`: missing or invalid operator ID.
- board loads but SR detail fails: endpoint-specific backend or BlueFolder data issue.

## Presentation Script

RouteDesk is dispatch's operating layer. BlueFolder stays the record, but RouteDesk turns dispatch work into an actionable board. Dispatchers identify as OpsHub operators, not Discord users, and OpsHub handles the BlueFolder connection centrally.

## Preflight

- browser hard refreshed after rebuild
- Settings operator ID set
- API base correct
- known SR available
- no stale `403` message after setting operator ID
- route order checked before opening Maps or route tools
