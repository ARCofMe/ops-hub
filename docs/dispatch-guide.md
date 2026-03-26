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

### `/dispatch_attention`

Use this when:

- you want jobs that need attention now
- you want to filter by stage or technician

This is one of the best commands for active triage.

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
3. Use `/dispatch_next` for specific follow-up guidance
4. Use `/customer` when you need the right contact information
5. Use `/photo_compliance_board` when photo follow-up matters
