# Parts Guide

This guide covers the parts workflows in Ops Hub.

## BlueFolder-Native Parts Commands

- `/parts_brief`
- `/parts_notes`
- `/missing_part`
- `/damaged_part`
- `/part_ordered`
- `/part_eta`
- `/part_tracking`
- `/part_received`
- `/part_ready`

These are the primary parts workflow commands because BlueFolder remains the main business record.

## Reading Parts Status

### `/parts_brief`

Use:

- `/parts_brief sr_id:95956`

Use this when:

- you want a quick parts summary
- you want the current normalized parts stage
- you want the recommended next action

### `/parts_notes`

Use this when:

- you want the recent BlueFolder parts note history

## Writing Parts Updates

### `/missing_part`

Use this when:

- a needed part is missing

### `/damaged_part`

Use this when:

- a needed part is damaged or unusable

### `/part_ordered`

Use this when:

- the part has been ordered
- vendor and ETA are known

### `/part_eta`

Use this when:

- ETA has changed or is now known

### `/part_tracking`

Use this when:

- tracking is available

### `/part_received`

Use this when:

- the part has arrived

### `/part_ready`

Use this when:

- the SR is ready to move back toward scheduling

## Supplemental Queue Commands

These are still available when internal coordination is useful:

- `/part`
- `/part_request_detail`
- `/part_requests`
- `/part_update`
- `/part_claim`
- `/part_unclaim`
- `/part_sync`
- `/part_reconcile`

These are supplemental to the BlueFolder-centered process, not the main long-term record.
