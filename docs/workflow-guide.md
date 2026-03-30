# Workflow Guide

This guide explains the shared workflow-state system inside Ops Hub.

Use this if you need to understand:

- what an attention item is
- what the queue statuses mean
- how dispatch should use the queue controls
- how the policy runner decides when to send reminders

## Core Objects

Ops Hub now owns two important workflow objects:

- `attention_item`
- `parts_case`

`attention_item` is the dispatch-facing unit of follow-up work.

It answers:

- what SR needs action
- what stage it is in
- who currently owns follow-up
- whether the item is open, acknowledged, or snoozed
- what happened recently
- what the next action should be

`parts_case` is the SR-level parts summary that dispatch and parts can both work from.

## Attention Statuses

Attention items currently use these statuses:

- `open`
- `acknowledged`
- `snoozed`

### `open`

Use this when the item should remain visible to policy and dispatch follow-up.

### `acknowledged`

Use this when someone has seen the issue and is actively handling it.

This suppresses the normal urgent notice path for now, but the item still exists in the queue and metrics.

### `snoozed`

Use this when follow-up should intentionally wait until later.

Snoozed items are still tracked. If they remain urgent for too long, Ops Hub can send a suppressed-item reminder so they do not disappear forever.

## Dispatch Queue Commands

Queue inspection:

- `/dispatch_board`
- `/dispatch_attention`
- `/dispatch_next`
- `/attention_history`

Queue actions:

- `/attention_ack`
- `/attention_snooze`
- `/attention_assign`
- `/attention_clear_owner`
- `/attention_unsnooze`
- `/attention_reopen`

## Recommended Dispatch Flow

1. Start with `/dispatch_board` to see queue totals, status mix, ownership coverage, and urgent state.
2. Use `/dispatch_attention` to inspect the actual items.
3. Use `/attention_assign` when follow-up needs a named owner.
4. Use `/attention_ack` when the work is actively in motion and should stop firing the default urgent notice path.
5. Use `/attention_snooze` only when the next action is intentionally delayed.
6. Use `/attention_history` when the queue state looks surprising.
7. Use `/attention_reopen` or `/attention_unsnooze` when the item should return to active policy tracking.

## Policy Behavior

The workflow policy runner refreshes the queue and sends notices from the derived attention state.

Current policy behavior:

- new urgent open items route through the normal stage-based urgent topic
- reopened urgent items route through a reopened-specific topic
- long-suppressed urgent items route through a suppressed reminder topic

Examples:

- `dispatch.scheduling_attention`
- `dispatch.scheduling_attention.reopened`
- `dispatch.scheduling_attention.suppressed`

That means Ops Hub now distinguishes:

- fresh urgent work
- work that came back after manual reopening
- work that has stayed hidden too long behind acknowledgement or snooze state

## Metrics

Ops Hub now reports queue metrics in the normal operator surfaces.

Current metrics include:

- total attention items
- queue status mix
- stage mix
- age buckets
- assigned vs unassigned follow-up ownership
- urgent open vs urgent suppressed counts

See:

- `/dispatch_board`
- `/service_status`
- `/policy_status`

## Audit Trail

Queue actions are written into workflow events.

That means these changes are auditable:

- acknowledgement
- snooze
- owner assignment and owner clear
- unsnooze
- reopen
- policy notices
- suppressed reminders

Use `/attention_history` to inspect recent queue actions for one SR and stage.
