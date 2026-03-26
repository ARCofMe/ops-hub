# Ops Hub Cutover Checklist

Use this checklist when replacing the current beta Discord bot with Ops Hub in the real server.

## Before Cutover

- Confirm `.env` is complete:
  - `OPS_HUB_DISCORD_TOKEN`
  - `OPS_HUB_GUILD_ID`
  - BlueFolder credentials and path
  - technician / dispatch / parts / admin role IDs or user IDs
  - technician BlueFolder map
  - notification channel routing if desired
- Confirm the local wrapper paths exist:
  - `OPS_HUB_BLUEFOLDER_API_PATH`
  - `OPS_HUB_DISPATCH_PROJECT_PATH`
  - `OPS_HUB_PARTS_CANNON_PROJECT_PATH` if you want the supplemental queue handoff
- Run:

```bash
source .venv/bin/activate
PYTHONPATH=src pytest -q
```

- Verify the suite is green.

## Startup Check

- Start Ops Hub locally:

```bash
source .venv/bin/activate
PYTHONPATH=src python -m ops_hub
```

- Confirm:
  - no config validation failure
  - no import/runtime crash during startup
  - Discord login succeeds
  - command sync completes for the configured guild or globally

## Server Check

- Confirm the bot is present in the target Discord server.
- Confirm slash commands appear.
- Confirm role-based access behaves correctly for:
  - admin
  - technician
  - dispatch
  - parts

## Workflow Check

- Verify technician flows:
  - `/job`
  - `/assignments`
  - `/missing_part`
  - `/damaged_part`
- Verify dispatch flows:
  - `/tech_assignments`
  - `/tech_job`
  - `/dispatch_board`
  - `/dispatch_attention`
  - `/dispatch_next`
- Verify parts flows:
  - `/parts_brief`
  - `/parts_notes`
  - `/part_ordered`
  - `/part_eta`
  - `/part_tracking`
  - `/part_received`
  - `/part_ready`
- Verify admin/debug flows:
  - `/ops_status`
  - `/config_check`
  - `/service_status`
  - `/recent_notices`

## Notification Check

- Trigger at least one `parts.*` notice and confirm it routes to the expected channel.
- Trigger at least one `dispatch.*` notice and confirm it routes to the expected channel.
- Confirm fallback notices still reach `OPS_HUB_NOTIFICATION_CHANNEL_ID` if configured.

## Cutover

- Stop the current beta bot.
- Start Ops Hub with the production-intended `.env`.
- Watch logs during the first live command usage window.
- Keep the old bot available as a short rollback option until confidence is established.

## Immediate Rollback Triggers

- BlueFolder auth or request failures across multiple commands
- slash commands missing or unsynced
- role access behaving incorrectly
- notices routing to the wrong place
- dispatcher or parts commands producing misleading output in live use

## After Cutover

- Capture the first real issues seen by:
  - technicians
  - dispatch
  - parts
  - admin
- Patch those issues in Ops Hub, not in the old bot.
