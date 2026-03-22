# Ops Hub Milestones

This document is the working milestone checklist for Ops Hub as it moves from migration scaffold to primary operations bot.

## Versioning Guide

- `V0.0.x`
  - Internal checkpoints
  - Architecture still moving
  - Commands and workflows may still shift materially
- `V0.1.0`
  - First coherent operator-facing beta
  - Core command model and access model feel intentional
- `V0.5.0`
  - Most major subsystems have real operational value
  - Migration seams are stable and used regularly
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
- [x] Operator/admin/dispatcher access tiers exist
- [x] Operator mapping persistence exists
- [ ] Photo ingest direction is redefined
- [ ] Dispatcher-only workflow surface is defined
- [ ] Primary workflows are considered stable

## Next Patch Tags (`V0.0.x`)

Use patch tags while the app is still moving quickly but each increment is worth preserving.

### Checklist

- [ ] A small set of related commits is complete and tested
- [ ] Docs reflect the new behavior
- [ ] No known broken command path remains in the changed area
- [ ] The increment would be useful to roll back to or refer to later

## Milestone: `V0.1.0`

Treat this as the first real Ops Hub beta.

### Product Shape

- [ ] Core command surface is intentionally defined
- [ ] `/job` behavior is stable enough for regular users
- [ ] `/part` behavior is stable enough for regular users
- [ ] Access tiers are settled enough that frequent changes are no longer expected
- [ ] Operator mapping workflow is usable without hand-editing env values
- [ ] Photo ingest direction is decided, even if not fully complete

### Integration Shape

- [ ] BlueFolder read-only integration is dependable
- [ ] Dispatch integration does more than stop preview and assignment presence
- [ ] Parts wrapper has at least one real workflow path
- [ ] Notification routing model is defined beyond dry-run logging

### Operational Shape

- [ ] README is current
- [ ] `.env.example` is current and understandable
- [ ] Admin/debug commands are sufficient for basic troubleshooting
- [ ] Another team member could stand the bot up from docs and config

## Milestone: `V0.5.0`

Treat this as the point where Ops Hub is clearly useful in daily work.

### Workflow Coverage

- [ ] BlueFolder lookups are broadly useful
- [ ] Dispatch workflows are genuinely actionable
- [ ] Parts workflows include real operational actions
- [ ] Photo ingest replacement direction is implemented enough to use
- [ ] Notification routing reaches actual destination channels or users

### Stability

- [ ] Access model is no longer experimental
- [ ] Mapping workflow is stable and not frequently redesigned
- [ ] Command output format is mostly stable
- [ ] Error paths are predictable and operator-friendly

## Milestone: `V1.0.0`

Treat this as the point where Ops Hub is the primary operations bot, not the migration scaffold.

### Product Readiness

- [ ] Main operational workflows are trusted in normal use
- [ ] The bot identity and command surface are intentionally finalized
- [ ] Major subsystems are no longer “placeholder” in normal usage

### Engineering Readiness

- [ ] Deployment/runtime process is repeatable
- [ ] Config model is stable
- [ ] Documentation is operationally complete
- [ ] Observability is sufficient for production support
- [ ] The app can tolerate real failures without confusing users

### Migration Readiness

- [ ] Existing projects are wrapped or superseded in the right places
- [ ] Remaining external dependencies are understood and intentional
- [ ] Ops Hub is the default entry point for operations work

## Recommended Near-Term Sequence

1. Define dispatcher-specific workflows beyond generic `/job`
2. Expand mapped assignment workflows
3. Revisit photo ingest after the revised concept is ready
4. Introduce real notification delivery targets
5. Decide what should qualify as `V0.1.0`
