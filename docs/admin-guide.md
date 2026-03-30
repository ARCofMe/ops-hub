# Admin Guide

This guide covers the admin and support commands in Ops Hub.

## Main Admin Commands

- `/ops_status`
- `/config_check`
- `/service_status`
- `/recent_notices`
- `/policy_status`
- `/policy_preview`
- `/policy_run_now`
- `/bluefolder_techs`
- `/export_member_map`
- `/suggest_tech_map`
- `/lookup_member`
- `/technician_mappings`
- `/export_technician_mappings`
- `/import_technician_mappings`
- `/reload_technician_mappings`
- `/set_technician_mapping`
- `/remove_technician_mapping`
- `/command_access`
- `/photo_features`
- `/set_photo_feature`
- `/clear_photo_feature`

## What These Are For

### Runtime and config

- `/ops_status`
- `/config_check`
- `/service_status`

Use these when:

- the bot looks unhealthy
- commands are missing expected data
- you need to verify wiring without exposing secrets

### Notices and routing

- `/recent_notices`
- `/policy_status`
- `/policy_preview`
- `/policy_run_now`

Use this when:

- you want to confirm dispatch or parts notices are firing
- you want to see urgent open vs urgent suppressed counts
- you want to see whether urgent items are missing an explicit owner
- you want to preview policy behavior without sending live notices
- you want to force one policy cycle during support or cutover work

### Workflow-state visibility

- `/service_status`
- `/policy_status`

Use these when:

- you need the current queue status mix
- you want to confirm follow-up owner coverage
- you want to see whether urgent work is open or currently suppressed
- you need to confirm that reopened or suppressed-reminder behavior is working

### Technician mapping management

- `/bluefolder_techs`
- `/export_member_map`
- `/suggest_tech_map`
- `/lookup_member`
- `/technician_mappings`
- `/import_technician_mappings`
- `/set_technician_mapping`
- `/remove_technician_mapping`
- `/export_technician_mappings`
- `/reload_technician_mappings`

Use these when:

- a technician is not resolving correctly
- a Discord user needs to map to a BlueFolder tech id
- you need to export the current Discord member list for review
- you want a suggested Discord-to-BlueFolder mapping to start from

### Feature flags

- `/photo_features`
- `/set_photo_feature`
- `/clear_photo_feature`

Use these when:

- a photo-related feature needs to be enabled or disabled safely

## Good Admin Habits

- verify mappings before debugging role problems
- use `service_status` before assuming a BlueFolder bug
- use `policy_preview` before `policy_run_now` when testing routing changes
- check `policy_status` and `recent_notices` together when validating escalation behavior
- keep feature toggles explicit when testing risky workflows
- patch issues in Ops Hub, not in the older bot
