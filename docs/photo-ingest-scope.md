# Photo Ingest Scope

Photo ingest is intentionally **out of scope for the `V0.1.0` Ops Hub beta**.

This is not a cancellation. It is a product-scope decision:

- the concept is being revised before implementation resumes
- Ops Hub should reach a coherent beta first around job, assignment, parts, admin, and notification workflows
- the listener can now archive Discord photo attachments through the configured email handoff

## What This Means for `V0.1.0`

- No real photo ingest processing is expected in the beta
- No compliance enforcement or attachment routing is expected in the beta
- No production claims should be made about photo ingest behavior

## What Is Still Allowed

- keep the ingest channel config in place for future direct BlueFolder upload/compliance expansion
- keep the service and adapter boundary in place
- evolve the design later without forcing a rewrite of the current bot foundation

## Planned Return Criteria

Photo ingest should come back into active implementation only after:

1. the revised intake concept is settled
2. the expected channel/user flow is clear
3. the compliance rules are clear enough to test
4. the data handoff target is known

Until then, Ops Hub should treat photo ingest as a deferred subsystem rather than a partially implemented feature.
