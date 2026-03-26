# Technician Guide

This guide covers the main technician commands in Ops Hub.

## Daily Commands

- `/job`
- `/assignments`
- `/customer`
- `/route_map`

## Looking Up Your Work

### `/job`

Use:

- `/job` with no reference to see your current assignment context
- `/job reference:95956` to look up a specific service request

Use this when:

- you want the current job summary
- you want dispatch and parts context for an SR

### `/assignments`

Use:

- `/assignments`

Use this when:

- you want a simpler list of today’s assigned jobs

### `/customer`

Use:

- `/customer sr_id:95956`

Use this when:

- you need the customer name
- you need the service location
- you need phone/contact information

## Field Update Commands

These commands write updates back to BlueFolder.

### `/eta`

Example:

- `/eta sr_id:95956 minutes:20`

Use this when:

- you know your estimated arrival time

### `/enroute`

Example:

- `/enroute sr_id:95956`
- `/enroute sr_id:95956 minutes:20`

Use this when:

- you are heading to the job
- you want to include ETA in one update

### `/start`

Example:

- `/start sr_id:95956`
- `/start sr_id:95956 details:Beginning diagnosis`

Use this when:

- you begin work at the job

### `/no_answer`

Example:

- `/no_answer sr_id:95956`
- `/no_answer sr_id:95956 details:Knocked twice and called once`

Use this when:

- the customer does not answer

### `/not_home`

Example:

- `/not_home sr_id:95956 details:Tenant not at location`

Use this when:

- the customer or occupant is not there

### `/reschedule_needed`

Example:

- `/reschedule_needed sr_id:95956 reason:Need return visit after tenant availability is confirmed`

Use this when:

- dispatch needs to follow up and move the job

### `/note`

Example:

- `/note sr_id:95956 details:Unit pulled out and vent path inspected`

Use this when:

- you need a quick general field note
- there is not a more specific command for the situation

## Parts-Related Technician Commands

- `/missing_part`
- `/damaged_part`
- `/parts_brief`
- `/parts_notes`
- `/part_request`
- `/my_part_requests`

Use the specific parts commands when possible instead of a generic note.

## Photo Commands

- `/mdlsn`
- `/photo_archive`
- `/photo_status`

Use `/mdlsn` for model/serial image attachment to the SR.

Use `/photo_archive` for the archive-mailbox handoff flow.

Use `/photo_status` to check whether photo mail has been found for the SR.

## Recommended Daily Flow

1. Run `/job` or `/assignments`
2. Use `/customer` if you need contact details
3. Use `/enroute` and `/start` during the call
4. Use `/missing_part` or `/damaged_part` if needed
5. Use `/mdlsn` or `/photo_archive` when photos are needed
6. Use `/note` only when no more specific command fits
