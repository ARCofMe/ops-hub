# Dispatch Guide

This guide covers the main dispatch workflows in Ops Hub.

## Main Commands

- `/job`
- `/assignments`
- `/customer`
- `/tech_assignments`
- `/tech_job`
- `/dispatch_board`
- `/dispatch_attention`
- `/attention_ack`
- `/attention_snooze`
- `/attention_assign`
- `/attention_clear_owner`
- `/attention_unsnooze`
- `/attention_reopen`
- `/attention_history`
- `/dispatch_next`
- `/photo_compliance_board`

## Looking Up A Specific Job

### `/job`

Use:

- `/job reference:95956`

Use this when:

- you want the SR summary
- you want parts status in the same response
- you want dispatch context without opening BlueFolder first

### `/customer`

Use:

- `/customer sr_id:95956`

Use this when:

- you need customer contact information
- you need to confirm who should be called
- you need to check location details

## Looking Up A Technician

### `/tech_assignments`

Use this when:

- you want one technician’s assignment list

### `/tech_job`

Use this when:

- you want one technician’s relationship to a specific SR

## Team-Level Dispatch Views

### `/dispatch_board`

Use this when:

- you want a team view across mapped technicians
- you want to see who is active today
- you want queue counts, status mix, owner coverage, and urgent suppression at a glance

### `/dispatch_attention`

Use this when:

- you want jobs that need attention now
- you want to filter by stage or technician
- you want to inspect follow-up owner, status, snooze state, and next action

This is one of the best commands for active triage.

Stage filters currently include:

- `issue_reported`
- `part_received`
- `part_ready`
- `quote_needed`

Use `quote_needed` when you want jobs that still need quote delivery, approval, landlord contact, or prepayment before scheduling can move.

## Queue Actions

### `/attention_ack`

Use this when:

- you have seen the item
- follow-up is actively in motion
- you want to suppress the normal urgent notice path for now

### `/attention_snooze`

Use this when:

- follow-up should intentionally wait
- you do not want the item treated as open right now

Do not use this as a substitute for ownership. If a person is working it now, use `/attention_assign` and usually `/attention_ack`.

### `/attention_assign`

Use this when:

- one person should clearly own next follow-up
- you want queue ownership to show up in board metrics and detail views

### `/attention_clear_owner`

Use this when:

- the current follow-up owner is no longer correct
- ownership should return to the queue

### `/attention_unsnooze`

Use this when:

- the wait period is over
- the item should return to active queue handling without a full reopen flow

### `/attention_reopen`

Use this when:

- acknowledged or snoozed work needs to go back to active policy tracking
- you want reopened urgent work to be treated as active escalation again

### `/attention_history`

Use this when:

- the current queue state does not make sense
- you want to see acknowledgement, snooze, owner, reopen, and policy reminder events for one SR

### `/dispatch_next`

Use:

- `/dispatch_next sr_id:95956`

Use this when:

- you want the current parts stage
- you want the recommended next action for dispatch

## Photo Compliance

### `/photo_compliance_board`

Use this when:

- you want to see current jobs missing required photos
- you want to follow up with technicians before jobs move further

## Practical Dispatch Flow

1. Use `/dispatch_board` for the day view
2. Use `/dispatch_attention` for actionable jobs
3. Use `/attention_assign` to make ownership explicit
4. Use `/attention_ack` or `/attention_snooze` to reflect real queue state
5. Use `/attention_history` if the status looks wrong or stale
6. Use `/dispatch_next` for specific follow-up guidance
7. Use `/customer` when you need the right contact information
8. Use `/photo_compliance_board` when photo follow-up matters

For jobs in a quote path:

1. Use `/dispatch_attention stage:quote_needed`
2. Use `/customer` to confirm who should be contacted
3. Assign an owner with `/attention_assign`
4. Acknowledge it once the quote or approval path is actively in motion
5. Reopen it if customer or landlord approval falls through and the item needs active escalation again

## Policy Behavior

Ops Hub policy now distinguishes:

- newly urgent open work
- reopened urgent work
- urgent work with no explicit follow-up owner
- long-suppressed urgent work

That means queue actions are not just cosmetic. They affect:

- what gets routed
- what gets suppressed
- what gets re-escalated later

If you want the detailed system behavior, see `workflow-guide.md`.
