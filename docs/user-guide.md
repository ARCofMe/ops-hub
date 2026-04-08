# Ops Hub User Guide

This guide is for people using Ops Hub inside Discord, especially if they are not already comfortable with Discord bots or slash commands.

## What Ops Hub Is

Ops Hub is the business Discord bot for operational workflows.

It helps the team:

- look up service requests
- check assignments
- send technician updates
- review parts status
- manage parts updates
- check photo status
- manage dispatch follow-up queues

Ops Hub does not replace BlueFolder as the main business record. It works alongside BlueFolder and writes important updates back to it.

## Basic Discord Use

Ops Hub is used with slash commands.

Example:

- type `/job`
- Discord will show the command and its inputs
- choose the command
- fill in the fields
- press Enter

Most Ops Hub replies are **ephemeral**.

That means:

- only you can see the reply
- the reply is not posted for the whole channel to read

## Common Terms

- `SR` means `Service Request`
- `SR id` means the BlueFolder service request number, such as `95956`
- `Dispatch` means the scheduling/coordinating team
- `Parts` means the team managing parts ordering and updates

## Starting Point

If you are not sure what command to use:

- run `/help`

Then go to the role guide that matches your job:

- `technician-guide.md`
- `dispatch-guide.md`
- `parts-guide.md`
- `admin-guide.md`
- `workflow-guide.md` if you need to understand queue status and policy behavior
- `discord-command-reference.md` if you need the full command inventory

## Typical Use Pattern

1. Look up the job with `/job` or `/customer`
2. Send field updates as needed
3. Check parts status if parts are involved
4. If you are dispatch, work from the queue views instead of only one-off lookups
5. Upload or archive photos when needed

## Good Habits

- Use the SR id directly when you have it
- Keep notes short and specific
- Use the purpose-built commands instead of one generic note when possible
- If dispatch follow-up is involved, prefer queue actions like acknowledge, assign, or snooze over “mental tracking”
- If a command gives a confusing result, copy the exact output and report it

## If Something Goes Wrong

Common cases:

- command does not show up
- command says you do not have permission
- no result is returned for an SR you know exists
- a route map or photo action fails

See `troubleshooting.md`.
