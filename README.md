# Ops Hub

Ops Hub is the new unified Discord-facing operations application for the business.

This project is the start of a migration path, not a rewrite. It creates a clean home for the long-term Discord bot while existing projects continue to remain intact and act as the current source of truth.

## Migration Philosophy

- Existing projects remain untouched.
- Ops Hub wraps and integrates existing projects incrementally.
- Parts Cannon is the internal codename for the parts-related subsystem and the broader migration effort.
- Ops Hub is the user-facing application name and the long-term platform direction.

The longer-term milestone checklist lives in `docs/milestones.md`.
Photo ingest beta scope notes live in `docs/photo-ingest-scope.md`.

## Goals

- One Discord bot identity.
- Modular internal services.
- Clean separation between bot, services, integrations, and core utilities.
- Production-minded Python foundation that is easy to test and extend.

## Project Layout

```text
ops-hub/
├── .env.example
├── pyproject.toml
├── README.md
├── src/
│   └── ops_hub/
│       ├── __init__.py
│       ├── __main__.py
│       ├── main.py
│       ├── bot/
│       │   ├── __init__.py
│       │   ├── client.py
│       │   ├── extensions.py
│       │   └── cogs/
│       │       ├── __init__.py
│       │       ├── health.py
│       │       └── operations.py
│       ├── core/
│       │   ├── __init__.py
│       │   ├── config.py
│       │   ├── container.py
│       │   └── logging.py
│       ├── integrations/
│       │   ├── __init__.py
│       │   ├── bluefolder_adapter.py
│       │   ├── dispatch_adapter.py
│       │   ├── parts_cannon_adapter.py
│       │   └── photo_ingest_adapter.py
│       ├── models/
│       │   ├── __init__.py
│       │   └── requests.py
│       └── services/
│           ├── __init__.py
│           ├── bluefolder.py
│           ├── dispatch.py
│           ├── notifications.py
│           ├── parts_cannon.py
│           └── photo_ingest.py
└── tests/
    └── __init__.py
```

## Quick Start

```bash
cd ops-hub
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
python -m ops_hub
```

Once `OPS_HUB_DISCORD_TOKEN` is set, the bot should start and register the current Ops Hub command surface.

For the first real BlueFolder read-only integration, set `OPS_HUB_BLUEFOLDER_API_PATH` to the local `bluefolder-api` repository root and provide either `OPS_HUB_BLUEFOLDER_ACCOUNT_NAME` or `OPS_HUB_BLUEFOLDER_BASE_URL` plus `OPS_HUB_BLUEFOLDER_API_KEY`.

## Current Commands

- `/ping`
- `/job`
- `/assignments`
- `/tech_assignments`
- `/tech_job`
- `/part`
- `/part_request`
- `/my_part_requests`
- `/part_requests`
- `/part_request_detail`
- `/part_update`
- `/part_claim`
- `/part_unclaim`
- `/part_sync`
- `/ops_status`
- `/config_check`
- `/service_status`
- `/recent_notices`
- `/operator_mappings`
- `/export_operator_mappings`
- `/reload_operator_mappings`
- `/set_operator_mapping`
- `/remove_operator_mapping`
- `/command_access`
- `/ops_help`

`/job` now supports two modes:
- pass a reference like `SR-100` for a direct lookup
- omit the reference to show the mapped technician's current assignments

Assignment summaries now include:
- assignment count
- mapped origin when available
- richer route/window/start context when the dispatch wrapper provides it

Dispatcher-focused commands now exist explicitly instead of relying only on shared commands:

- `/assignments`
- `/tech_assignments`
- `/tech_job`

## Role Terms

Ops Hub currently uses one internal technical label that does not perfectly match business wording:

- `operator` in config/code currently maps most closely to `technician` in business terms

So, in business-facing language, the intended role vocabulary is:

- `Admin`
- `Parts`
- `Dispatch`
- `Technician`

Today, the code/config distinguishes:

- `Admin`
- `Parts`
- `Dispatcher`
- `Operator` (technician-facing)

That naming can be cleaned up later in code, but the README should be read using the business terms above.

## Command Access Model

- Admin-only:
  - `/ops_status`
  - `/config_check`
  - `/service_status`
  - `/recent_notices`
  - `/operator_mappings`
  - `/export_operator_mappings`
  - `/reload_operator_mappings`
  - `/set_operator_mapping`
  - `/remove_operator_mapping`
  - `/command_access`
- Technician, Dispatch, and Admin:
  - `/job`
  - `/assignments`
- Technician, Parts, and Admin:
  - `/part_request`
  - `/my_part_requests`
- Dispatch and Admin:
  - `/tech_assignments`
  - `/tech_job`
- Parts and Admin:
  - `/part`
  - `/part_requests`
  - `/part_request_detail`
  - `/part_update`
  - `/part_claim`
  - `/part_unclaim`
  - `/part_sync`
  - `unsynced_only` filtering is available on `/part_requests`
- Open bot health:
  - `/ping`
  - `/ops_help`

Current hierarchy:

1. `Admin`
2. `Dispatch`, `Parts`, and `Technician`
3. open utility health command access

Current implementation note:

- `OPS_HUB_OPERATOR_*` config values currently represent technician-facing access
- `OPS_HUB_PARTS_*` config values represent parts-facing access
- `OPS_HUB_DISPATCHER_*` config values represent dispatch-facing access

Ops Hub currently uses config-backed user/role lists for admin, technician-facing operator, parts, and dispatcher scope decisions.

## Operator Mappings

Ops Hub can map Discord users to BlueFolder user IDs in two ways.

Business term note:

- these are effectively technician mappings today, even though the internal config key still says `operator`

- inline environment config via `OPS_HUB_OPERATOR_BLUEFOLDER_USER_MAP`
- optional JSON persistence via `OPS_HUB_OPERATOR_MAPPING_FILE`

The merged mapping set is used for:

- technician-aware `/job` context
- mapped current-assignment lookup when `/job` is called without a reference
- technician-specific dispatch context such as assignment presence and origin address
- technician-created parts request records that can carry mapped BlueFolder user context later

If `OPS_HUB_OPERATOR_MAPPING_FILE` is set, the admin mapping commands can export and reload mappings from disk.

## Current Scaffold Scope

- Discord bot foundation with `discord.py`
- structured logging
- environment-backed settings
- dependency wiring container
- current service layer for:
  - BlueFolder
  - Parts Cannon
  - photo ingest
  - dispatch
  - notifications
- operator directory and mapping persistence
- integration adapters for wrapping existing local projects incrementally

## How Migration Will Work

Ops Hub does not replace current projects immediately. Instead:

1. existing project logic stays where it is
2. Ops Hub defines service interfaces and adapters around those projects
3. Discord commands call Ops Hub services
4. individual behaviors can be moved or rewritten later only when it is safe and worth it

This keeps the foundation clean while allowing gradual adoption.

## Current Status

- BlueFolder has a real read-only lookup path
- dispatch can build a stop preview and mapped technician context through the existing routing project
- dispatch now has dedicated dispatcher-facing commands instead of relying only on shared operations commands
- parts now has a lightweight tracked request lifecycle with create, list, and update flows
- technicians can submit and review their own parts requests while Parts manages the shared queue
- parts queue ownership is now explicit through claim/unclaim and detailed request inspection
- parts can now export the tracked queue to a downstream handoff file under the configured Parts project path
- parts queue records now track last sync state so unsynced work can be filtered directly
- notifications can optionally route to a configured Discord channel instead of staying logger-only
- admin service status now reports live parts queue counts in addition to adapter status
- the bot now includes `/ops_help` as an in-bot command guide for the stable beta surface
- photo ingest remains intentionally paused while the concept is being revised
- technician/admin/dispatch/parts access is now explicit instead of implicit

## Next Practical Moves

1. keep strengthening mapped assignment workflows around real dispatch use
2. build on the downstream queue handoff with a real consuming parts workflow or project wrapper
3. revisit photo ingest once the revised concept is settled
