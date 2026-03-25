# Ops Hub

Ops Hub is a unified Discord operations bot for the appliance repair business.

It gives the team one Discord-facing surface for technician, dispatch, parts, and admin workflows while keeping the internals modular and testable.

## What It Does

Ops Hub currently focuses on:

- BlueFolder job lookups and service request context
- technician assignment views
- dispatcher assignment, board, triage, and next-action views
- BlueFolder-native parts comment/update flows
- tracked internal parts queue workflows where supplemental coordination is useful
- admin/debug visibility for runtime, config, mappings, and service state

BlueFolder remains the primary business source of truth for operational job and parts updates. Ops Hub is the Discord workflow layer around that process.

## Current Roles

Business-facing role model:

- `Admin`
- `Dispatch`
- `Parts`
- `Technician`

Current implementation note:

- `OPS_HUB_TECHNICIAN_*` settings are technician-facing
- `OPS_HUB_DISPATCHER_*` settings are dispatch-facing
- `OPS_HUB_PARTS_*` settings are parts-facing

## Current Commands

Open utility commands:

- `/ping`
- `/help`

Technician / dispatch / admin:

- `/job`
- `/assignments`
- `/customer`

Dispatch / admin:

- `/tech_assignments`
- `/tech_job`
- `/dispatch_board`
- `/dispatch_attention`
- `/dispatch_next`

Technician / parts / admin:

- `/part_request`
- `/my_part_requests`
- `/missing_part`
- `/damaged_part`

Technician / admin:

- `/route_map`
- `/eta`
- `/enroute`
- `/start`
- `/no_answer`
- `/not_home`
- `/reschedule_needed`
- `/note`
- `/mdlsn`
- `/photo_archive`

Technician / parts / dispatch / admin:

- `/parts_brief`
- `/parts_notes`
- `/photo_status`

Parts / admin:

- `/part`
- `/part_requests`
- `/part_request_detail`
- `/part_update`
- `/part_claim`
- `/part_unclaim`
- `/part_sync`
- `/part_reconcile`
- `/part_ordered`
- `/part_eta`
- `/part_tracking`
- `/part_received`
- `/part_ready`

Admin only:

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

## Key Workflows

### Job And Assignment Lookup

- `/job` supports direct SR lookup
- `/job` also supports mapped self-context when no reference is provided
- `/assignments` shows the current mapped technician assignment view
- `/customer` gives a quick SR customer/location snapshot in the field
- dispatch has dedicated one-tech, team-board, triage, and next-action views

### Technician Field Updates

Ops Hub can log fast field updates directly back to BlueFolder and route notices to dispatch when needed:

- `/eta`
- `/enroute`
- `/start`
- `/no_answer`
- `/not_home`
- `/reschedule_needed`
- `/note`

These commands are intentionally shaped as workflow events so future side effects like customer SMS can be added without changing the command model.

### BlueFolder-Native Parts Flow

Ops Hub supports the parts comment/update lifecycle directly against BlueFolder:

- `/parts_brief`
- `/parts_notes`
- `/missing_part`
- `/damaged_part`
- `/part_ordered`
- `/part_eta`
- `/part_tracking`
- `/part_received`
- `/part_ready`

This aligns the bot with the real business workflow instead of forcing a separate parallel system.

The BlueFolder-native path also supports:

- normalized lifecycle stage summaries
- recommended next-action guidance
- dispatcher attention filtering by stage or technician

### Supplemental Internal Parts Queue

Ops Hub also has an internal tracked parts queue for coordination where it helps:

- `/part_request`
- `/my_part_requests`
- `/part_requests`
- `/part_request_detail`
- `/part_update`
- `/part_claim`
- `/part_unclaim`
- `/part_sync`
- `/part_reconcile`

That queue is supplemental. The long-term direction is still BlueFolder-centered operations.

## Quick Start

```bash
cd ops-hub
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
python -m ops_hub
```

Once `OPS_HUB_DISCORD_TOKEN` is set, the bot should start and register the current command surface.

To enable BlueFolder integration, set:

- `OPS_HUB_BLUEFOLDER_API_PATH`
- `OPS_HUB_BLUEFOLDER_API_KEY`
- either `OPS_HUB_BLUEFOLDER_ACCOUNT_NAME` or `OPS_HUB_BLUEFOLDER_BASE_URL`

To enable Discord notice routing, optionally set:

- `OPS_HUB_NOTIFICATION_CHANNEL_ID` for a default notice channel
- `OPS_HUB_NOTIFICATION_CHANNEL_MAP` to route topic families like `parts` or `dispatch` to specific channels

## Project Layout

```text
ops-hub/
├── .env.example
├── pyproject.toml
├── README.md
├── docs/
│   ├── milestones.md
│   └── photo-ingest-scope.md
├── src/
│   └── ops_hub/
│       ├── bot/
│       ├── core/
│       ├── integrations/
│       ├── models/
│       └── services/
└── tests/
```

Key areas:

- `src/ops_hub/bot/`: Discord client and cogs
- `src/ops_hub/services/`: business/service layer
- `src/ops_hub/integrations/`: wrappers around external/local systems
- `src/ops_hub/core/`: config, logging, and dependency wiring
- `tests/`: regression coverage

## Development

Typical local loop:

```bash
source .venv/bin/activate
PYTHONPATH=src pytest -q
```

The codebase is structured to keep bot behavior, service logic, and integration boundaries separate so workflows can be tested without coupling everything to Discord or external systems.

## Docs

Longer-form project and planning docs live in `docs/`:

- `docs/milestones.md`
- `docs/photo-ingest-scope.md`
- `docs/cutover-checklist.md`

## Project Direction

Ops Hub is the app and platform name.

`Parts Cannon` is an internal codename for the parts-related subsystem and the broader migration effort, but the bot itself is not limited to parts workflows.
