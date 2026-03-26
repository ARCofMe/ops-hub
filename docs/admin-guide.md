# Admin Guide

This guide covers the admin and support commands in Ops Hub.

## Main Admin Commands

- `/ops_status`
- `/config_check`
- `/service_status`
- `/recent_notices`
- `/technician_mappings`
- `/export_technician_mappings`
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

Use this when:

- you want to confirm dispatch or parts notices are firing

### Technician mapping management

- `/technician_mappings`
- `/set_technician_mapping`
- `/remove_technician_mapping`
- `/export_technician_mappings`
- `/reload_technician_mappings`

Use these when:

- a technician is not resolving correctly
- a Discord user needs to map to a BlueFolder tech id

### Feature flags

- `/photo_features`
- `/set_photo_feature`
- `/clear_photo_feature`

Use these when:

- a photo-related feature needs to be enabled or disabled safely

## Good Admin Habits

- verify mappings before debugging role problems
- use `service_status` before assuming a BlueFolder bug
- keep feature toggles explicit when testing risky workflows
- patch issues in Ops Hub, not in the older bot
