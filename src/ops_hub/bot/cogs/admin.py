"""Admin and debug slash commands."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from difflib import SequenceMatcher

import discord
from discord import app_commands
from discord.ext import commands

from ops_hub.bot.client import OpsHubBot


def _normalize_name(raw: str | None) -> str:
    """Return a casefolded alphanumeric name for loose matching."""
    text = " ".join(str(raw or "").split()).strip().casefold()
    return "".join(char for char in text if char.isalnum() or char.isspace()).strip()


def _member_name_candidates_from_record(member: dict[str, object]) -> list[str]:
    """Return normalized Discord name candidates for one member record."""
    candidates: list[str] = []
    for raw in [member.get("display_name"), member.get("global_name"), member.get("username")]:
        normalized = _normalize_name(str(raw or ""))
        if normalized and normalized not in candidates:
            candidates.append(normalized)
    return candidates


def _matching_techs_for_member_record(
    member: dict[str, object],
    techs: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Return exact normalized-name BlueFolder matches for a Discord member."""
    techs_by_name: dict[str, list[dict[str, object]]] = {}
    for tech in techs:
        normalized = _normalize_name(str(tech.get("name") or ""))
        if normalized:
            techs_by_name.setdefault(normalized, []).append(tech)

    unique_matches: dict[int, dict[str, object]] = {}
    for candidate in _member_name_candidates_from_record(member):
        for tech in techs_by_name.get(candidate, []):
            tech_id = int(tech.get("id") or 0)
            if tech_id:
                unique_matches[tech_id] = tech
    return list(unique_matches.values())


def _near_match_techs_for_member_record(
    member: dict[str, object],
    techs: list[dict[str, object]],
    *,
    threshold: float = 0.84,
) -> list[dict[str, object]]:
    """Return close BlueFolder name matches for manual review."""
    candidates = _member_name_candidates_from_record(member)
    scored: list[tuple[float, dict[str, object]]] = []
    for tech in techs:
        tech_name = _normalize_name(str(tech.get("name") or ""))
        if not tech_name:
            continue
        best = max((SequenceMatcher(None, candidate, tech_name).ratio() for candidate in candidates), default=0.0)
        if best >= threshold:
            scored.append((best, tech))

    scored.sort(key=lambda item: (-item[0], str(item[1].get("name") or "")))
    unique: dict[int, dict[str, object]] = {}
    for score, tech in scored[:5]:
        tech_id = int(tech.get("id") or 0)
        if tech_id and tech_id not in unique:
            unique[tech_id] = {
                "id": tech_id,
                "name": tech.get("name"),
                "score": round(score, 3),
            }
    return list(unique.values())


def _build_tech_map_suggestion(
    members: list[dict[str, object]],
    techs: list[dict[str, object]],
) -> dict[str, object]:
    """Build exact and near-match mapping suggestions from Discord members to BlueFolder techs."""
    suggested_map: dict[str, int] = {}
    matched: list[dict[str, object]] = []
    ambiguous: list[dict[str, object]] = []
    near_matches: list[dict[str, object]] = []
    unmatched_discord: list[dict[str, object]] = []
    matched_tech_ids: set[int] = set()

    for member in members:
        unique_matches = _matching_techs_for_member_record(member, techs)

        if len(unique_matches) == 1:
            tech = unique_matches[0]
            tech_id = int(tech["id"])
            suggested_map[str(member["discord_user_id"])] = tech_id
            matched_tech_ids.add(tech_id)
            matched.append(
                {
                    "discord_user_id": member["discord_user_id"],
                    "display_name": member.get("display_name"),
                    "username": member.get("username"),
                    "bluefolder_user_id": tech_id,
                    "bluefolder_name": tech.get("name"),
                }
            )
        elif len(unique_matches) > 1:
            ambiguous.append(
                {
                    "discord_user_id": member["discord_user_id"],
                    "display_name": member.get("display_name"),
                    "username": member.get("username"),
                    "candidate_bluefolder_users": [
                        {"id": int(tech["id"]), "name": tech.get("name")}
                        for tech in unique_matches
                    ],
                }
            )
        else:
            nearby = _near_match_techs_for_member_record(member, techs)
            if nearby:
                near_matches.append(
                    {
                        "discord_user_id": member["discord_user_id"],
                        "display_name": member.get("display_name"),
                        "username": member.get("username"),
                        "candidate_bluefolder_users": nearby,
                    }
                )
            unmatched_discord.append(member)

    unmatched_bluefolder = [
        {"id": int(tech["id"]), "name": tech.get("name"), "email": tech.get("email")}
        for tech in techs
        if int(tech.get("id") or 0) not in matched_tech_ids
    ]

    return {
        "suggested_discord_tech_map": suggested_map,
        "suggested_discord_tech_map_env": (
            "OPS_HUB_TECHNICIAN_BLUEFOLDER_USER_MAP="
            f"{json.dumps(suggested_map, separators=(',', ':'))}"
        ),
        "matched": matched,
        "ambiguous": ambiguous,
        "near_matches": near_matches,
        "unmatched_discord": unmatched_discord,
        "unmatched_bluefolder": unmatched_bluefolder,
    }


def _coerce_mapping_dict(raw: object) -> dict[int, int]:
    """Validate and coerce a mapping payload into integer Discord/BlueFolder ids."""
    if not isinstance(raw, dict):
        raise ValueError("Mapping payload must be a JSON object.")

    parsed: dict[int, int] = {}
    for raw_discord_user_id, raw_bluefolder_user_id in raw.items():
        try:
            discord_user_id = int(str(raw_discord_user_id).strip())
            bluefolder_user_id = int(str(raw_bluefolder_user_id).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError("Mapping payload must contain only integer Discord and BlueFolder user IDs.") from exc
        if discord_user_id <= 0 or bluefolder_user_id <= 0:
            raise ValueError("Mapping payload must contain only positive Discord and BlueFolder user IDs.")
        parsed[discord_user_id] = bluefolder_user_id
    return parsed


def _parse_mapping_import_text(text: str) -> dict[int, int]:
    """Parse a mapping import artifact from JSON or env-assignment text."""
    raw_text = text.strip()
    if not raw_text:
        raise ValueError("Mapping import file is empty.")

    for prefix in ["OPS_HUB_TECHNICIAN_BLUEFOLDER_USER_MAP=", "DISCORD_TECH_MAP="]:
        if raw_text.startswith(prefix):
            raw_text = raw_text[len(prefix):].strip()
            break

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError("Mapping import file must contain valid JSON or an env assignment line.") from exc

    if isinstance(payload, dict):
        for key in ["suggested_discord_tech_map", "technician_bluefolder_user_map", "mappings"]:
            if key in payload:
                return _coerce_mapping_dict(payload[key])
        return _coerce_mapping_dict(payload)

    raise ValueError("Mapping import file must contain a JSON object.")


def _summarize_mapping_import(
    current: dict[int, int],
    incoming: dict[int, int],
    *,
    mode: str,
) -> dict[str, object]:
    """Return a concise preview of what a mapping import would change."""
    if mode not in {"merge", "replace"}:
        raise ValueError("Import mode must be merge or replace.")

    added = 0
    updated = 0
    unchanged = 0
    removed = 0
    sample_lines: list[str] = []

    for discord_user_id, bluefolder_user_id in sorted(incoming.items()):
        current_value = current.get(discord_user_id)
        if current_value is None:
            added += 1
            if len(sample_lines) < 8:
                sample_lines.append(f"add: <@{discord_user_id}> -> BlueFolder `{bluefolder_user_id}`")
        elif current_value == bluefolder_user_id:
            unchanged += 1
        else:
            updated += 1
            if len(sample_lines) < 8:
                sample_lines.append(
                    f"update: <@{discord_user_id}> BlueFolder `{current_value}` -> `{bluefolder_user_id}`"
                )

    if mode == "replace":
        for discord_user_id, bluefolder_user_id in sorted(current.items()):
            if discord_user_id not in incoming:
                removed += 1
                if len(sample_lines) < 8:
                    sample_lines.append(f"remove: <@{discord_user_id}> -> BlueFolder `{bluefolder_user_id}`")

    return {
        "mode": mode,
        "incoming_count": len(incoming),
        "current_count": len(current),
        "added": added,
        "updated": updated,
        "unchanged": unchanged,
        "removed": removed,
        "sample_lines": sample_lines,
    }


class AdminCog(commands.Cog):
    """Operational visibility commands for bot admins and maintainers."""

    def __init__(self, bot: OpsHubBot) -> None:
        self.bot = bot

    async def cog_app_command_check(self, interaction: discord.Interaction) -> bool:
        """Restrict admin/debug commands to configured Ops Hub admins."""
        if self._is_admin(interaction):
            return True
        raise app_commands.CheckFailure("You do not have permission to use this command.")

    @app_commands.command(name="ops_status", description="Show current Ops Hub runtime status.")
    async def ops_status(self, interaction: discord.Interaction) -> None:
        """Report high-level runtime and wiring status."""
        await self._send_message(interaction, self._build_ops_status())

    @app_commands.command(name="config_check", description="Show configuration and path wiring status.")
    async def config_check(self, interaction: discord.Interaction) -> None:
        """Report current config shape without exposing secrets."""
        await self._send_message(interaction, self._build_config_check())

    @app_commands.command(name="service_status", description="Show current integration and service states.")
    async def service_status(self, interaction: discord.Interaction) -> None:
        """Report current service-layer status from the configured adapters."""
        await self._send_deferred_message(interaction, await self._build_service_status())

    @app_commands.command(name="recent_notices", description="Show the most recent Ops Hub notices.")
    async def recent_notices(self, interaction: discord.Interaction) -> None:
        """Report recent dry-run notices captured by the notification service."""
        await self._send_message(interaction, await self._build_recent_notices())

    @app_commands.command(name="policy_status", description="Show current workflow policy status and urgent items.")
    async def policy_status(self, interaction: discord.Interaction) -> None:
        """Report the current workflow policy snapshot."""
        await self._send_deferred_message(interaction, await self._build_policy_status())

    @app_commands.command(name="policy_preview", description="Preview the current workflow policy cycle without sending notices.")
    async def policy_preview(self, interaction: discord.Interaction) -> None:
        """Preview policy results without emitting notices."""
        await self._send_deferred_message(interaction, await self._build_policy_preview())

    @app_commands.command(name="policy_run_now", description="Run the workflow policy cycle immediately.")
    async def policy_run_now(self, interaction: discord.Interaction) -> None:
        """Execute the workflow policy cycle now."""
        await self._send_deferred_message(interaction, await self._build_policy_run_now())

    @app_commands.command(name="technician_mappings", description="Show current technician to BlueFolder mappings.")
    async def technician_mappings(self, interaction: discord.Interaction) -> None:
        """Show the merged technician mapping set."""
        await self._send_message(interaction, self._build_technician_mappings())

    @app_commands.command(name="bluefolder_techs", description="List active BlueFolder technicians and IDs.")
    async def bluefolder_techs(self, interaction: discord.Interaction) -> None:
        """Show active BlueFolder technicians and export them for review."""
        await self._send_deferred_message(interaction, await self._build_bluefolder_techs())

    @app_commands.command(name="export_member_map", description="Export Discord member identities to a JSON file.")
    @app_commands.describe(scope="Export all guild members or only members visible in this channel.")
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="guild", value="guild"),
            app_commands.Choice(name="channel", value="channel"),
        ]
    )
    async def export_member_map(self, interaction: discord.Interaction, scope: str = "guild") -> None:
        """Write a Discord member snapshot to disk for mapping review."""
        await self._send_deferred_message(interaction, await self._build_export_member_map(interaction, scope))

    @app_commands.command(name="suggest_tech_map", description="Suggest technician mappings by comparing Discord names to BlueFolder techs.")
    @app_commands.describe(scope="Compare all guild members or only members visible in this channel.")
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="guild", value="guild"),
            app_commands.Choice(name="channel", value="channel"),
        ]
    )
    async def suggest_tech_map(self, interaction: discord.Interaction, scope: str = "guild") -> None:
        """Write a suggested technician-map export and env snippet."""
        await self._send_deferred_message(interaction, await self._build_suggest_tech_map(interaction, scope))

    @app_commands.command(name="lookup_member", description="Inspect one Discord member's technician mapping status.")
    @app_commands.describe(user="Discord member to inspect.")
    async def lookup_member(self, interaction: discord.Interaction, user: discord.Member) -> None:
        """Inspect a member against current mappings and BlueFolder tech matches."""
        await self._send_deferred_message(interaction, await self._build_lookup_member(user))

    @app_commands.command(name="export_technician_mappings", description="Persist technician mappings to the configured file.")
    async def export_technician_mappings(self, interaction: discord.Interaction) -> None:
        """Write current technician mappings to disk."""
        await self._send_message(interaction, self._build_export_technician_mappings())

    @app_commands.command(name="import_technician_mappings", description="Import technician mappings from a JSON or env-style artifact.")
    @app_commands.describe(
        path="Path to a JSON or .env-style mapping artifact.",
        mode="Merge into current mappings or replace the file-backed set.",
        confirm="Preview only unless true.",
    )
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="merge", value="merge"),
            app_commands.Choice(name="replace", value="replace"),
        ]
    )
    async def import_technician_mappings(
        self,
        interaction: discord.Interaction,
        path: str,
        mode: str = "merge",
        confirm: bool = False,
    ) -> None:
        """Import technician mappings from disk into the configured file-backed store."""
        await self._send_message(interaction, self._build_import_technician_mappings(path, mode=mode, confirm=confirm))

    @app_commands.command(name="reload_technician_mappings", description="Reload technician mappings from the configured file.")
    async def reload_technician_mappings(self, interaction: discord.Interaction) -> None:
        """Reload file-backed technician mappings."""
        await self._send_message(interaction, self._build_reload_technician_mappings())

    @app_commands.command(name="set_technician_mapping", description="Set a Discord user to BlueFolder user mapping.")
    async def set_technician_mapping(
        self,
        interaction: discord.Interaction,
        discord_user_id: int,
        bluefolder_user_id: int,
    ) -> None:
        """Create or update a technician mapping."""
        await self._send_message(interaction, self._build_set_technician_mapping(discord_user_id, bluefolder_user_id))

    @app_commands.command(name="remove_technician_mapping", description="Remove a Discord user to BlueFolder user mapping.")
    async def remove_technician_mapping(self, interaction: discord.Interaction, discord_user_id: int) -> None:
        """Remove a technician mapping."""
        await self._send_message(interaction, self._build_remove_technician_mapping(discord_user_id))

    @app_commands.command(name="command_access", description="Show the current command access model.")
    async def command_access(self, interaction: discord.Interaction) -> None:
        """Report command scope definitions for admins/technicians/dispatchers."""
        await self._send_message(interaction, self._build_command_access())

    @app_commands.command(name="photo_features", description="Show current photo workflow feature flags.")
    async def photo_features(self, interaction: discord.Interaction) -> None:
        """Show effective photo feature states."""
        await self._send_message(interaction, self._build_photo_features())

    @app_commands.command(name="set_photo_feature", description="Enable or disable a photo workflow feature.")
    @app_commands.choices(
        feature=[
            app_commands.Choice(name="mdlsn_upload", value="mdlsn_upload"),
            app_commands.Choice(name="photo_archive_handoff", value="photo_archive_handoff"),
            app_commands.Choice(name="photo_mailbox_scan", value="photo_mailbox_scan"),
            app_commands.Choice(name="weekly_missing_photo_notices", value="weekly_missing_photo_notices"),
        ]
    )
    async def set_photo_feature(self, interaction: discord.Interaction, feature: str, enabled: bool) -> None:
        """Persist a photo feature override."""
        await self._send_message(interaction, self._build_set_photo_feature(feature, enabled))

    @app_commands.command(name="clear_photo_feature", description="Clear a photo feature override and revert to env default.")
    @app_commands.choices(
        feature=[
            app_commands.Choice(name="mdlsn_upload", value="mdlsn_upload"),
            app_commands.Choice(name="photo_archive_handoff", value="photo_archive_handoff"),
            app_commands.Choice(name="photo_mailbox_scan", value="photo_mailbox_scan"),
            app_commands.Choice(name="weekly_missing_photo_notices", value="weekly_missing_photo_notices"),
        ]
    )
    async def clear_photo_feature(self, interaction: discord.Interaction, feature: str) -> None:
        """Clear a persisted photo feature override."""
        await self._send_message(interaction, self._build_clear_photo_feature(feature))

    async def _send_message(self, interaction: discord.Interaction, message: str) -> None:
        """Send a standard ephemeral admin response."""
        await interaction.response.send_message(message, ephemeral=True)

    async def _send_deferred_message(self, interaction: discord.Interaction, message: str) -> None:
        """Send a standard deferred ephemeral admin response."""
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(message, ephemeral=True)

    def _build_ops_status(self) -> str:
        """Render a concise runtime status summary."""
        settings = self.bot.settings
        lines = [
            "Ops Hub Status",
            f"Environment: `{settings.environment}`",
            f"Guild sync: {'guild' if settings.guild_id is not None else 'global'}",
            f"Configured guild id: `{settings.guild_id}`" if settings.guild_id is not None else "Configured guild id: not set",
            (
                f"Workflow policy runner: enabled every `{settings.workflow_policy_interval_seconds}`s"
                if settings.enable_workflow_policy_runner
                else "Workflow policy runner: disabled"
            ),
            f"Photo ingest listener channel: `{settings.photo_ingest_channel_id}`"
            if settings.photo_ingest_channel_id is not None
            else "Photo ingest listener channel: not set",
        ]
        if self.bot.user is None:
            lines.append("Bot identity: not connected")
        else:
            lines.append(f"Bot identity: `{self.bot.user}` (`{self.bot.user.id}`)")
        return "\n".join(lines)

    def _build_config_check(self) -> str:
        """Render secret-safe configuration visibility for operators."""
        settings = self.bot.settings
        lines = [
            "Ops Hub Config Check",
            f"Discord token: {'set' if bool(settings.discord_token.strip()) else 'missing'}",
            f"Log level: `{settings.log_level}`",
            (
                f"Notification channel: `{settings.notification_channel_id}`"
                if settings.notification_channel_id is not None
                else "Notification channel: not set"
            ),
            f"BlueFolder credentials: {self._bluefolder_config_status()}",
            self._path_line("BlueFolder library path", settings.bluefolder_api_path),
            self._path_line("Parts Cannon path", settings.parts_cannon_project_path),
            self._path_line("Dispatch path", settings.dispatch_project_path),
            self._path_line("Photo ingest path", settings.photo_ingest_project_path),
            self._path_line("Photo feature flags file", settings.photo_feature_flags_file),
        ]
        return "\n".join(lines)

    async def _build_service_status(self) -> str:
        """Render current service-level adapter results."""
        bluefolder = await self.bot.container.bluefolder_service.get_job_summary("SR-100")
        dispatch = await self.bot.container.dispatch_service.adapter.get_job("SR-100")
        parts = await self.bot.container.parts_cannon_service.adapter.get_part_status("SR-100")
        parts_queue = self.bot.container.parts_cannon_service.queue_summary()
        photo = await self.bot.container.photo_ingest_service.status()
        notifications = await self.bot.container.notification_service.status()
        lines = [
            "Ops Hub Service Status",
            f"BlueFolder: `{bluefolder.integration_status}`",
            f"BlueFolder detail: {bluefolder.message}",
            f"Dispatch: `{dispatch.integration_status}`",
            f"Dispatch detail: {dispatch.message}",
            f"Parts Cannon: `{parts.integration_status}`",
            f"Parts Cannon detail: {parts.message}",
            f"Parts queue open: `{parts_queue.open_requests}` of `{parts_queue.total_requests}` total",
            f"Parts queue assigned/unassigned: `{parts_queue.assigned_requests}` / `{parts_queue.unassigned_requests}`",
            f"Parts queue synced: `{parts_queue.synced_requests}`",
            "Parts queue status counts: "
            f"requested `{parts_queue.requested_count}`, "
            f"ordered `{parts_queue.ordered_count}`, "
            f"received `{parts_queue.received_count}`, "
            f"resolved `{parts_queue.resolved_count}`, "
            f"cancelled `{parts_queue.cancelled_count}`",
            f"Photo ingest: `{photo.get('status', 'unknown')}`",
            f"Photo ingest source: `{photo.get('source', 'unknown')}`",
            f"Photo ingest mode: `{photo.get('mode', 'unknown')}`",
            f"Photo ingest listener: `{photo.get('listener', 'unknown')}`",
            f"Photo ingest upload: `{photo.get('upload', 'unknown')}`",
            f"Photo ingest archive: `{photo.get('archive', 'unknown')}`",
            f"Photo ingest mailbox: `{photo.get('mailbox', 'unknown')}`",
            f"Notifications: `{notifications.mode}` via `{notifications.transport}`",
            f"Notification notices sent: `{notifications.notice_count}`",
            f"Last notification topic: `{notifications.last_topic or 'none'}`",
        ]
        workflow_snapshot = self.bot.container.workflow_state_service.current_snapshot()
        workflow_metrics = self.bot.container.workflow_state_service.attention_metrics(workflow_snapshot)
        lines.extend(
            [
                f"Workflow attention items: `{len(workflow_snapshot.attention_items)}`",
                f"Workflow parts cases: `{len(workflow_snapshot.parts_cases)}`",
                f"Workflow events: `{len(workflow_snapshot.events)}`",
                "Workflow attention status: "
                + ", ".join(
                    f"{status} `{count}`" for status, count in sorted(workflow_metrics["status_counts"].items())
                )
                if workflow_metrics["status_counts"]
                else "Workflow attention status: unavailable",
                (
                    "Workflow urgent state: "
                    f"open `{workflow_metrics['urgent_open_items']}`, "
                    f"suppressed `{workflow_metrics['urgent_suppressed_items']}`"
                ),
            ]
        )
        features = photo.get("features", "")
        if features:
            lines.append("Photo features:")
            lines.extend(features.split(", "))
        else:
            lines.append("Photo features: unavailable")
        return "\n".join(lines)

    async def _build_recent_notices(self, limit: int = 5) -> str:
        """Render the most recent notification attempts."""
        notices = await self.bot.container.notification_service.recent_notices(limit=limit)
        if not notices:
            return "Recent Notices\nNo notices have been recorded yet."

        lines = ["Recent Notices"]
        for notice in notices:
            lines.append(f"`{notice.topic}` via `{notice.delivery}`")
            lines.append(notice.message)
        return "\n".join(lines)

    async def _build_policy_status(self) -> str:
        """Render current workflow policy state and urgent queue items."""
        snapshot = self.bot.container.workflow_state_service.current_snapshot()
        metrics = self.bot.container.workflow_state_service.attention_metrics(snapshot)
        urgent_items = [item for item in snapshot.attention_items if item.age_bucket == "urgent" and item.status == "open"]
        lines = [
            "Workflow Policy Status",
            (
                f"Runner: enabled every `{self.bot.settings.workflow_policy_interval_seconds}`s"
                if self.bot.settings.enable_workflow_policy_runner
                else "Runner: disabled"
            ),
            f"Attention items: `{len(snapshot.attention_items)}`",
            f"Parts cases: `{len(snapshot.parts_cases)}`",
            f"Workflow events: `{len(snapshot.events)}`",
            f"Urgent open items: `{metrics['urgent_open_items']}`",
            f"Urgent suppressed items: `{metrics['urgent_suppressed_items']}`",
        ]
        if metrics["status_counts"]:
            lines.extend(["", "Queue status"])
            for status, count in sorted(metrics["status_counts"].items()):
                lines.append(f"{status}: `{count}`")
        lines.extend(
            [
                "",
                "Follow-up ownership",
                f"Assigned owners: `{metrics['assigned_owner_items']}`",
                f"Unassigned owners: `{metrics['unassigned_owner_items']}`",
            ]
        )
        if urgent_items:
            lines.extend(["", "Urgent queue"])
            for item in urgent_items[:8]:
                lines.append(f"`{item.reference}` `{item.stage_label}` `{item.age_hours or 0}h`")
                if item.next_action:
                    lines.append(f"Next action: {item.next_action}")
        return "\n".join(lines)

    async def _build_policy_preview(self) -> str:
        """Preview the next policy cycle without sending notices."""
        summary = await self.bot.container.workflow_state_service.run_policy_cycle(emit_notices=False)
        return "\n".join(
            [
                "Workflow Policy Preview",
                f"Attention items: `{summary['attention_items']}`",
                f"Urgent items: `{summary['urgent_items']}`",
                f"Reopened urgent items: `{summary['reopened_urgent_items']}`",
                f"Owner-gap urgent items: `{summary['owner_gap_urgent_items']}`",
                f"Suppressed urgent items: `{summary['suppressed_urgent_items']}`",
                f"Topics routed: `{summary['topics_count']}`",
                "Notices sent: `0`",
            ]
        )

    async def _build_policy_run_now(self) -> str:
        """Run the workflow policy cycle immediately and report the result."""
        summary = await self.bot.container.workflow_state_service.run_policy_cycle(emit_notices=True)
        return "\n".join(
            [
                "Workflow Policy Run",
                f"Attention items: `{summary['attention_items']}`",
                f"Urgent items: `{summary['urgent_items']}`",
                f"Reopened urgent items: `{summary['reopened_urgent_items']}`",
                f"Owner-gap urgent items: `{summary['owner_gap_urgent_items']}`",
                f"Suppressed urgent items: `{summary['suppressed_urgent_items']}`",
                f"Topics routed: `{summary['topics_count']}`",
                f"Notices sent: `{summary['notices_sent']}`",
                f"Suppressed reminders sent: `{summary['suppressed_reminders_sent']}`",
            ]
        )

    def _bluefolder_config_status(self) -> str:
        """Summarize whether BlueFolder credentials are minimally configured."""
        settings = self.bot.settings
        has_key = bool((settings.bluefolder_api_key or "").strip())
        has_account = bool((settings.bluefolder_account_name or "").strip())
        has_base_url = bool((settings.bluefolder_base_url or "").strip())
        if has_key and (has_account or has_base_url):
            return "configured"
        if has_key or has_account or has_base_url:
            return "partial"
        return "not set"

    def _build_technician_mappings(self) -> str:
        """Render the current merged technician mapping set."""
        records = self.bot.container.technician_directory_service.mapping_records()
        if not records:
            return "Technician Mappings\nNo technician mappings are currently configured."

        lines = ["Technician Mappings"]
        for record in records:
            lines.append(
                self.bot.container.technician_directory_service.technician_label(
                    discord_user_id=record.discord_user_id,
                    bluefolder_user_id=record.bluefolder_user_id,
                )
            )
        return "\n".join(lines)

    async def _build_bluefolder_techs(self) -> str:
        """Render and export the currently visible BlueFolder technician directory."""
        techs = await self._active_bluefolder_techs()
        if not techs:
            return (
                "BlueFolder Technicians\n"
                "No active BlueFolder technician list is currently available. "
                "The tenant user-directory endpoint may be unavailable."
            )

        payload = {
            "bluefolder_tech_count": len(techs),
            "techs": techs,
        }
        export_path = self._write_json_export("bluefolder_techs", payload)

        lines = [
            f"BlueFolder Technicians (`{len(techs)}`)",
            f"Exported JSON: `{export_path}`",
        ]
        for tech in techs[:20]:
            lines.append(f"`{tech['id']}` {tech['name']}")
        if len(techs) > 20:
            lines.append(f"...and `{len(techs) - 20}` more in the export.")
        return "\n".join(lines)

    async def _build_export_member_map(self, interaction: discord.Interaction, scope: str) -> str:
        """Export Discord member records in the requested scope."""
        records = await self._collect_members(interaction, scope=scope)
        payload = {
            "guild_id": str(interaction.guild_id or ""),
            "scope": scope,
            "member_count": len(records),
            "members": records,
            "technician_map_template": {item["discord_user_id"]: None for item in records},
        }
        export_path = self._write_json_export("member_map", payload)
        return f"Wrote `{len(records)}` member records to `{export_path}`."

    async def _build_suggest_tech_map(self, interaction: discord.Interaction, scope: str) -> str:
        """Build a suggested technician mapping export from Discord members and BlueFolder techs."""
        records = await self._collect_members(interaction, scope=scope)
        techs = await self._active_bluefolder_techs()
        if not techs:
            return (
                "Could not build a technician-map suggestion because no active BlueFolder tech list is available."
            )

        suggestion = _build_tech_map_suggestion(records, techs)
        payload = {
            "guild_id": str(interaction.guild_id or ""),
            "scope": scope,
            "member_count": len(records),
            "bluefolder_tech_count": len(techs),
            **suggestion,
        }
        suggestion_path = self._write_json_export("suggested_tech_map", payload)
        env_path = self._write_text_export(
            "technician_map",
            f"{suggestion['suggested_discord_tech_map_env']}\n",
            extension=".env",
        )
        return (
            f"Wrote suggested map to `{suggestion_path}` and env snippet to `{env_path}`. "
            f"Matched `{len(suggestion['matched'])}`, ambiguous `{len(suggestion['ambiguous'])}`, "
            f"near matches `{len(suggestion['near_matches'])}`, "
            f"unmatched Discord `{len(suggestion['unmatched_discord'])}`, "
            f"unmatched BlueFolder `{len(suggestion['unmatched_bluefolder'])}`."
        )

    async def _build_lookup_member(self, user: discord.Member) -> str:
        """Render one member's current technician-mapping status."""
        techs = await self._active_bluefolder_techs()
        record = self._discord_member_record_from_member(user)
        direct_map = self.bot.container.technician_directory_service.mappings().get(user.id)
        matched_techs = _matching_techs_for_member_record(record, techs)

        lines = [
            f"Discord user: {record['display_name']} (@{record['username']})",
            f"Discord ID: `{user.id}`",
        ]
        role_names = sorted(str(name) for name in (record.get("role_names") or []))
        if role_names:
            lines.append("Roles: " + ", ".join(role_names))
        if direct_map:
            mapped_tech = next((tech for tech in techs if int(tech.get("id") or 0) == int(direct_map)), None)
            if mapped_tech:
                lines.append(f"Mapped explicitly: {mapped_tech['name']} (BlueFolder `{mapped_tech['id']}`)")
            else:
                lines.append(f"Mapped explicitly: BlueFolder `{direct_map}` (not found in active tech list)")
        else:
            lines.append("Mapped explicitly: no")

        if len(matched_techs) == 1:
            tech = matched_techs[0]
            lines.append(f"Name-based match: {tech['name']} (BlueFolder `{tech['id']}`)")
        elif len(matched_techs) > 1:
            lines.append(
                "Name-based matches: "
                + ", ".join(f"{tech['name']} (`{tech['id']}`)" for tech in matched_techs[:5])
            )
        else:
            near_matches = _near_match_techs_for_member_record(record, techs)
            if near_matches:
                lines.append(
                    "Near matches: "
                    + ", ".join(
                        f"{tech['name']} (`{tech['id']}`, score `{tech['score']}`)"
                        for tech in near_matches
                    )
                )
            else:
                lines.append("Name-based match: none")
        return "\n".join(lines)

    def _build_export_technician_mappings(self) -> str:
        """Persist current mappings to disk and report the result."""
        path = self.bot.container.technician_directory_service.export_mappings()
        if path is None:
            return "Technician mapping export is not configured. Set OPS_HUB_TECHNICIAN_MAPPING_FILE first."
        return f"Exported technician mappings to `{path}`."

    def _build_import_technician_mappings(self, path: str, *, mode: str = "merge", confirm: bool = False) -> str:
        """Import technician mappings from a JSON or env-style artifact on disk."""
        if mode not in {"merge", "replace"}:
            return "Import mode must be `merge` or `replace`."

        file_path = Path(path).expanduser()
        if not file_path.exists():
            return f"Technician mapping import file was not found: `{file_path}`."
        if not file_path.is_file():
            return f"Technician mapping import path is not a file: `{file_path}`."

        try:
            imported = _parse_mapping_import_text(file_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return f"Could not import technician mappings: {exc}"

        current = self.bot.container.technician_directory_service.mappings()
        summary = _summarize_mapping_import(current, imported, mode=mode)
        lines = [
            f"Technician mapping import preview for `{file_path}`",
            f"Mode: `{mode}`",
            f"Incoming mappings: `{summary['incoming_count']}`",
            f"Current merged mappings: `{summary['current_count']}`",
            f"Additions: `{summary['added']}`",
            f"Updates: `{summary['updated']}`",
            f"Unchanged: `{summary['unchanged']}`",
        ]
        if mode == "replace":
            lines.append(f"Removals from current merged set: `{summary['removed']}`")
        sample_lines = list(summary["sample_lines"])
        if sample_lines:
            lines.append("")
            lines.append("Examples:")
            lines.extend(sample_lines)
        if not confirm:
            lines.extend(
                [
                    "",
                    "Preview only. Re-run with `confirm:true` to write these mappings.",
                ]
            )
            return "\n".join(lines)

        persisted_path = self.bot.container.technician_directory_service.import_mappings(
            imported,
            replace=(mode == "replace"),
        )
        if persisted_path is None:
            return "Technician mapping import is not configured. Set OPS_HUB_TECHNICIAN_MAPPING_FILE first."

        total = len(self.bot.container.technician_directory_service.mappings())
        lines.extend(
            [
                "",
                f"Imported `{len(imported)}` technician mappings.",
                f"Current merged mapping count: `{total}`.",
                f"Persisted to `{persisted_path}`.",
            ]
        )
        return "\n".join(lines)

    def _build_reload_technician_mappings(self) -> str:
        """Reload file-backed mappings and report the result."""
        mappings = self.bot.container.technician_directory_service.reload_mappings()
        return f"Reloaded `{len(mappings)}` technician mappings."

    def _build_set_technician_mapping(self, discord_user_id: int, bluefolder_user_id: int) -> str:
        """Create or update a technician mapping."""
        self.bot.container.technician_directory_service.set_mapping(
            discord_user_id=discord_user_id,
            bluefolder_user_id=bluefolder_user_id,
        )
        label = self.bot.container.technician_directory_service.technician_label(
            discord_user_id=discord_user_id,
            bluefolder_user_id=bluefolder_user_id,
        )
        return f"Mapped {label}."

    def _build_remove_technician_mapping(self, discord_user_id: int) -> str:
        """Remove a technician mapping."""
        removed = self.bot.container.technician_directory_service.remove_mapping(discord_user_id=discord_user_id)
        if removed:
            return (
                "Removed technician mapping for "
                f"{self.bot.container.technician_directory_service.discord_mention(discord_user_id)}."
            )
        return (
            "No technician mapping existed for "
            f"{self.bot.container.technician_directory_service.discord_mention(discord_user_id)}."
        )

    def _build_command_access(self) -> str:
        """Render the current command access model."""
        return "\n".join(
            [
                "Command Access",
                "`/ops_status`, `/config_check`, `/service_status`, `/recent_notices`, `/policy_status`, `/policy_preview`, `/policy_run_now`, `/technician_mappings`, `/bluefolder_techs`, `/export_member_map`, `/suggest_tech_map`, `/lookup_member`, `/export_technician_mappings`, `/import_technician_mappings`, `/reload_technician_mappings`, `/set_technician_mapping`, `/remove_technician_mapping`, `/command_access`, `/photo_features`, `/set_photo_feature`, `/clear_photo_feature`: admin only",
                "`/job`, `/assignments`, `/customer`: technicians, dispatchers, admins",
                "`/eta`, `/enroute`, `/start`, `/no_answer`, `/not_home`, `/reschedule_needed`, `/note`: technicians, admins",
                "`/mdlsn`, `/photo_archive`: technicians, admins (if enabled)",
                "`/photo_status`: technicians, parts, dispatchers, admins (if mailbox scan is enabled)",
                "`/photo_reminder_check`: dispatchers, admins",
                "`/part_request`, `/my_part_requests`, `/missing_part`, `/damaged_part`: technicians, parts, admins",
                "`/parts_brief`, `/parts_notes`: technicians, parts, dispatchers, admins",
                "`/tech_assignments`, `/tech_job`, `/dispatch_board`, `/dispatch_attention`, `/attention_ack`, `/attention_snooze`, `/attention_assign`, `/attention_clear_owner`, `/attention_unsnooze`, `/attention_reopen`, `/attention_history`, `/dispatch_next`, `/photo_compliance_board`: dispatchers, admins",
                "`/part`, `/part_requests`, `/part_request_detail`, `/part_update`, `/part_claim`, `/part_unclaim`, `/part_sync`, `/part_reconcile`, `/part_ordered`, `/part_eta`, `/part_tracking`, `/part_received`, `/part_ready`: parts, admins",
                "`/ping`: open to anyone who can invoke the bot",
            ]
        )

    def _build_photo_features(self) -> str:
        """Render effective photo workflow feature states."""
        lines = ["Photo Features"]
        lines.extend(self.bot.container.photo_feature_flags_service.status_lines())
        return "\n".join(lines)

    def _build_set_photo_feature(self, feature: str, enabled: bool) -> str:
        """Persist a photo feature override."""
        try:
            self.bot.container.photo_feature_flags_service.set_override(feature, enabled)
        except ValueError as exc:
            return str(exc)
        state = "enabled" if enabled else "disabled"
        return f"Photo feature `{feature}` is now `{state}`."

    def _build_clear_photo_feature(self, feature: str) -> str:
        """Clear a persisted photo feature override."""
        try:
            removed = self.bot.container.photo_feature_flags_service.clear_override(feature)
        except ValueError as exc:
            return str(exc)
        if removed:
            return f"Cleared photo feature override for `{feature}`."
        return f"No override was set for `{feature}`."

    async def _active_bluefolder_techs(self) -> list[dict[str, object]]:
        """Return the active BlueFolder tech list in the old-bot-compatible shape."""
        directory = await self.bot.container.bluefolder_service.get_active_user_directory()
        return [
            {"id": user_id, "name": name, "email": None}
            for user_id, name in sorted(directory.items(), key=lambda item: item[1].casefold())
        ]

    async def _collect_members(
        self,
        interaction: discord.Interaction,
        *,
        scope: str,
    ) -> list[dict[str, object]]:
        """Collect Discord member records for the requested scope."""
        guild = interaction.guild
        if guild is None:
            return []

        try:
            members: list[discord.Member]
            if scope == "channel":
                channel = interaction.channel
                members = list(getattr(channel, "members", []) or [])
            else:
                members = [member async for member in guild.fetch_members(limit=None)]
        except Exception as exc:
            if scope == "channel":
                raise RuntimeError("Could not load Discord members visible in this channel.") from exc
            raise RuntimeError(
                "Could not load Discord guild members. Check Server Members Intent and bot permissions."
            ) from exc

        exported: list[dict[str, object]] = []
        for member in sorted(
            members,
            key=lambda item: (
                str(getattr(item, "display_name", "") or "").casefold(),
                str(getattr(item, "name", "") or "").casefold(),
                int(getattr(item, "id", 0) or 0),
            ),
        ):
            if getattr(member, "bot", False):
                continue
            exported.append(self._discord_member_record_from_member(member))
        return exported

    def _discord_member_record_from_member(self, member: discord.abc.User) -> dict[str, object]:
        """Return the exportable identity record for one Discord member."""
        return {
            "discord_user_id": str(member.id),
            "username": member.name,
            "display_name": getattr(member, "display_name", member.name),
            "global_name": getattr(member, "global_name", None),
            "role_names": sorted(
                role.name
                for role in getattr(member, "roles", [])
                if getattr(role, "name", None)
            ),
        }

    def _write_json_export(self, stem_suffix: str, payload: dict[str, object]) -> str:
        """Write one JSON export file and return its path."""
        path = self._export_output_path(stem_suffix=stem_suffix)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return str(path)

    def _write_text_export(self, stem_suffix: str, text: str, *, extension: str = ".txt") -> str:
        """Write one text export file and return its path."""
        path = self._export_output_path(stem_suffix=stem_suffix, extension=extension)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return str(path)

    def _export_output_path(self, *, stem_suffix: str, extension: str = ".json") -> Path:
        """Return the configured export output path for member/mapping admin artifacts."""
        configured = self.bot.settings.member_export_path
        base_path = Path(configured).expanduser() if configured else Path.cwd() / "exports" / "discord_members.json"
        stem = base_path.stem
        timestamp = ""
        if self.bot.settings.member_export_timestamped:
            timestamp = "_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        suffix = f"_{stem_suffix}" if stem_suffix else ""
        return base_path.with_name(f"{stem}{suffix}{timestamp}{extension}")

    def _path_line(self, label: str, path_value: str | None) -> str:
        """Render a filesystem path status line."""
        if not path_value:
            return f"{label}: not set"

        path = Path(path_value).expanduser()
        status = "exists" if path.exists() else "missing"
        return f"{label}: `{path}` ({status})"

    def _is_admin(self, interaction: discord.Interaction) -> bool:
        """Return whether the invoking user matches configured admin users or roles."""
        user = getattr(interaction, "user", None)
        user_id = getattr(user, "id", None)
        user_roles = getattr(user, "roles", None)
        role_ids = {getattr(role, "id", None) for role in user_roles or [] if getattr(role, "id", None) is not None}
        guild_permissions = getattr(user, "guild_permissions", None)
        has_administrator_permission = bool(getattr(guild_permissions, "administrator", False))
        guild = getattr(interaction, "guild", None)
        is_guild_owner = bool(guild is not None and getattr(guild, "owner_id", None) == user_id)
        if user_id is None:
            return False
        identity = self.bot.container.technician_directory_service.resolve_identity(
            user_id=user_id,
            role_ids=role_ids,
            has_administrator_permission=has_administrator_permission,
            is_guild_owner=is_guild_owner,
        )
        return identity.is_admin


async def setup(bot: OpsHubBot) -> None:
    """Load the admin cog."""
    await bot.add_cog(AdminCog(bot))
