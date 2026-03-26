# Troubleshooting

## Command Does Not Show Up

Check:

- the bot is online
- the command sync completed
- you restarted after command changes
- you are in the correct server

## Permission Denied

Check:

- your Discord roles
- your mapped technician/admin/dispatch/parts access
- `/command_access` for the intended scope

If needed, ask an admin to check mappings and role ids.

## Job Or Customer Not Found

Check:

- the SR id is correct
- BlueFolder is reachable
- the command did not return a BlueFolder status/error block

If the SR exists in BlueFolder but not in Ops Hub, report the exact command output.

## Route Map Problems

Check:

- the technician has current assignments
- BlueFolder returned mappable addresses
- the route-map provider is configured

If the preview fails, keep the text output and route link when available.

## Photo Problems

Check:

- the relevant photo feature is enabled
- the image uploaded successfully
- mailbox scan is enabled if using `/photo_status`

If a photo command fails, capture:

- the command used
- the SR id
- the visible Discord error
- the console error if available

## Notes Or Updates Fail To Write

Check:

- the user has a valid technician mapping when the command depends on BlueFolder note authorship
- BlueFolder credentials are valid
- the bot is using the local BlueFolder API path expected by Ops Hub

If the note fails, capture the exact terminal traceback and command used.
