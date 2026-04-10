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
- the `Next stop` card matches the expected stop
- service-window order is correct
- the active stop is not jumping to a PM stop before AM work

Then open `Queue` and confirm:

- stop order matches service windows
- route launch opens cleanly

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
- a workflow screen opens without a selected job
- photo attach messaging does not match the active backend
- a web app title or branding label is inconsistent
