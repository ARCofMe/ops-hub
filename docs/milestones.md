# Ops Hub Milestones

This document is the working milestone checklist for Ops Hub as it moves from migration scaffold to primary operations bot.

## Versioning Guide

- `V0.0.x`
  - Internal checkpoints
  - Architecture still moving
  - Commands and workflows may still shift materially
- `V0.1.0`
  - First coherent technician-facing beta
  - Core command model and access model feel intentional
  - Photo ingest is explicitly outside the beta scope
- `V0.5.0`
  - Most major subsystems have real operational value
  - Migration seams are stable and used regularly
  - Photo ingest remains outside milestone scope until the revised concept is ready
- `V1.0.0`
  - Ops Hub is the primary dependable operations bot
  - Main workflows are stable, documented, and trusted

## Current Baseline

- [x] Discord bot foundation exists
- [x] Startup config validation exists
- [x] Structured logging exists
- [x] Command error handling exists
- [x] BlueFolder read-only lookup exists
- [x] Dispatch stop preview exists
- [x] Parts wrapper boundary exists
- [x] Admin/debug commands exist
- [x] Technician/admin/dispatcher access tiers exist
- [x] Dedicated Parts access tier exists
- [x] Technician mapping persistence exists
- [x] Dedicated dispatcher command surface exists
- [ ] Photo ingest direction is redefined
- [x] Primary workflows are considered stable

## Next Patch Tags (`V0.0.x`)

Use patch tags while the app is still moving quickly but each increment is worth preserving.

### Checklist

- [x] A small set of related commits is complete and tested
- [x] Docs reflect the new behavior
- [x] No known broken command path remains in the changed area
- [x] The increment would be useful to roll back to or refer to later

### Current Recommendation

- `V0.1.0` is now a reasonable milestone tag for the first coherent beta.

## Milestone: `V0.1.0`

Treat this as the first real Ops Hub beta.

### Product Shape

- [x] Core command surface is intentionally defined
- [x] `/job` behavior is stable enough for regular users
- [x] `/assignments` and dispatcher-focused assignment flows are stable enough for regular users
- [x] `/part` behavior is stable enough for regular users
- [x] parts request submission, queue handling, and ownership flow are stable enough for regular users
- [x] Access tiers are settled enough that frequent changes are no longer expected
- [x] Technician mapping workflow is usable without hand-editing env values
- [x] Photo ingest is explicitly deferred from beta scope and documented

### Integration Shape

- [x] BlueFolder read-only integration is dependable
- [x] Dispatch integration does more than stop preview and assignment presence
- [x] Parts wrapper has at least one real workflow path
- [x] Parts request lifecycle is connected to a basic downstream handoff file
- [x] Parts request lifecycle is connected to a basic consuming downstream receipt loop
- [x] BlueFolder-native parts issue/update flows exist for the core business comment lifecycle
- [ ] BlueFolder-native parts flows cover enough live usage that the supplemental internal queue is clearly secondary
- [x] Notification routing model is defined beyond dry-run logging

### Operational Shape

- [x] README is current
- [x] `.env.example` is current and understandable
- [x] Admin/debug commands are sufficient for basic troubleshooting
- [x] Another team member could stand the bot up from docs and config

## Milestone: `V0.5.0`

Treat this as the point where Ops Hub is clearly useful in daily work.

### Workflow Coverage

- [x] BlueFolder lookups are broadly useful
- [x] Dispatch workflows are moving beyond basic previews into more actionable assignment context
- [x] Parts workflows include real operational actions
- [x] BlueFolder-native parts update flows cover the main business comment lifecycle
- [x] Photo ingest remains intentionally deferred outside the `V0.5.0` milestone scope
- [x] Notification routing reaches actual destination channels or users
- [x] BlueFolder-native parts summaries and updates are preferred as the primary active path, with the supplemental internal queue retained as support tooling

### Stability

- [x] Access model is no longer experimental
- [x] Mapping workflow is stable and not frequently redesigned
- [x] Command output format is mostly stable
- [x] Error paths are predictable and technician-friendly

### Current Recommendation

- `V0.5.0` is now a reasonable milestone tag for the current active scope:
  - BlueFolder-centered parts workflows
  - technician / dispatch / parts / admin command surfaces
  - dispatcher triage and next-action guidance
  - topic-based Discord notice routing

## Milestone: `V1.0.0`

Treat this as the point where Ops Hub is the primary operations bot, not the migration scaffold.

### Product Readiness

- [ ] Main operational workflows are trusted in normal use
- [ ] The bot identity and command surface are intentionally finalized
- [ ] Major subsystems are no longer “placeholder” in normal usage
- [ ] Ops Hub owns actionable workflow state instead of behaving mainly as a command wrapper
- [ ] Dispatch and parts can work from queue views and next-action state instead of comment archaeology
- [ ] Technician API and mobile workflows are first-class product surfaces

### Engineering Readiness

- [ ] Deployment/runtime process is repeatable
- [ ] Config model is stable
- [ ] Documentation is operationally complete
- [ ] Observability is sufficient for production support
- [ ] The app can tolerate real failures without confusing users
- [ ] Workflow events and state transitions are auditable across Discord and non-Discord surfaces

### Migration Readiness

- [ ] Existing projects are wrapped or superseded in the right places
- [ ] Remaining external dependencies are understood and intentional
- [ ] Ops Hub is the default entry point for operations work
- [ ] BlueFolder remains a system of record while Ops Hub clearly owns the system-of-action layer

## Recommended Near-Term Sequence

1. Build an attention engine so Ops Hub can derive actionable work instead of only surfacing source-system data
2. Build a first-class parts case model so parts state is owned cleanly inside Ops Hub
3. Promote dispatch from summaries into queue-based triage and next-action control
4. Expand the technician API into a real field workflow surface
5. Add metrics, escalation, and policy-driven follow-up
6. Revisit photo ingest after the revised concept is ready
