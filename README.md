# Ops Hub

Ops Hub is the new unified Discord-facing operations application for the business.

This project is the start of a migration path, not a rewrite. It creates a clean home for the long-term Discord bot while existing projects continue to remain intact and act as the current source of truth.

## Migration Philosophy

- Existing projects remain untouched.
- Ops Hub wraps and integrates existing projects incrementally.
- Parts Cannon is the internal codename for the parts-related subsystem and the broader migration effort.
- Ops Hub is the user-facing application name and the long-term platform direction.

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

Once `OPS_HUB_DISCORD_TOKEN` is set, the bot should start and register a basic `/ping` command plus placeholder `/job` and `/part` commands.

For the first real BlueFolder read-only integration, set `OPS_HUB_BLUEFOLDER_API_PATH` to the local `bluefolder-api` repository root and provide either `OPS_HUB_BLUEFOLDER_ACCOUNT_NAME` or `OPS_HUB_BLUEFOLDER_BASE_URL` plus `OPS_HUB_BLUEFOLDER_API_KEY`.

## Current Scaffold Scope

- Discord bot foundation with `discord.py`
- structured logging
- environment-backed settings
- dependency wiring container
- placeholder service layer for:
  - BlueFolder
  - Parts Cannon
  - photo ingest
  - dispatch
  - notifications
- placeholder integration adapters for wrapping existing local projects later

## How Migration Will Work

Ops Hub does not replace current projects immediately. Instead:

1. existing project logic stays where it is
2. Ops Hub defines service interfaces and adapters around those projects
3. Discord commands call Ops Hub services
4. individual behaviors can be moved or rewritten later only when it is safe and worth it

This keeps the foundation clean while allowing gradual adoption.

## Next Steps

1. config/env validation
2. Discord bot startup test
3. BlueFolder read-only adapter
4. photo ingest channel listener
5. parts workflow wrapper
