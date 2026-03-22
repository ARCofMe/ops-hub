"""Admin and debug slash commands."""

from __future__ import annotations

from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from ops_hub.bot.client import OpsHubBot


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
        await interaction.response.send_message(self._build_ops_status(), ephemeral=True)

    @app_commands.command(name="config_check", description="Show configuration and path wiring status.")
    async def config_check(self, interaction: discord.Interaction) -> None:
        """Report current config shape without exposing secrets."""
        await interaction.response.send_message(self._build_config_check(), ephemeral=True)

    @app_commands.command(name="service_status", description="Show current integration and service states.")
    async def service_status(self, interaction: discord.Interaction) -> None:
        """Report current service-layer status from the configured adapters."""
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(await self._build_service_status(), ephemeral=True)

    @app_commands.command(name="recent_notices", description="Show the most recent Ops Hub notices.")
    async def recent_notices(self, interaction: discord.Interaction) -> None:
        """Report recent dry-run notices captured by the notification service."""
        await interaction.response.send_message(await self._build_recent_notices(), ephemeral=True)

    @app_commands.command(name="operator_mappings", description="Show current operator to BlueFolder mappings.")
    async def operator_mappings(self, interaction: discord.Interaction) -> None:
        """Show the merged operator mapping set."""
        await interaction.response.send_message(self._build_operator_mappings(), ephemeral=True)

    @app_commands.command(name="export_operator_mappings", description="Persist operator mappings to the configured file.")
    async def export_operator_mappings(self, interaction: discord.Interaction) -> None:
        """Write current operator mappings to disk."""
        await interaction.response.send_message(self._build_export_operator_mappings(), ephemeral=True)

    @app_commands.command(name="reload_operator_mappings", description="Reload operator mappings from the configured file.")
    async def reload_operator_mappings(self, interaction: discord.Interaction) -> None:
        """Reload file-backed operator mappings."""
        await interaction.response.send_message(self._build_reload_operator_mappings(), ephemeral=True)

    @app_commands.command(name="set_operator_mapping", description="Set a Discord user to BlueFolder user mapping.")
    async def set_operator_mapping(
        self,
        interaction: discord.Interaction,
        discord_user_id: int,
        bluefolder_user_id: int,
    ) -> None:
        """Create or update an operator mapping."""
        await interaction.response.send_message(
            self._build_set_operator_mapping(discord_user_id, bluefolder_user_id),
            ephemeral=True,
        )

    @app_commands.command(name="remove_operator_mapping", description="Remove a Discord user to BlueFolder user mapping.")
    async def remove_operator_mapping(self, interaction: discord.Interaction, discord_user_id: int) -> None:
        """Remove an operator mapping."""
        await interaction.response.send_message(
            self._build_remove_operator_mapping(discord_user_id),
            ephemeral=True,
        )

    @app_commands.command(name="command_access", description="Show the current command access model.")
    async def command_access(self, interaction: discord.Interaction) -> None:
        """Report command scope definitions for admins/operators/dispatchers."""
        await interaction.response.send_message(self._build_command_access(), ephemeral=True)

    def _build_ops_status(self) -> str:
        """Render a concise runtime status summary."""
        settings = self.bot.settings
        lines = [
            "Ops Hub Status",
            f"Environment: `{settings.environment}`",
            f"Guild sync: {'guild' if settings.guild_id is not None else 'global'}",
            f"Configured guild id: `{settings.guild_id}`" if settings.guild_id is not None else "Configured guild id: not set",
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
            f"BlueFolder credentials: {self._bluefolder_config_status()}",
            self._path_line("BlueFolder library path", settings.bluefolder_api_path),
            self._path_line("Parts Cannon path", settings.parts_cannon_project_path),
            self._path_line("Dispatch path", settings.dispatch_project_path),
            self._path_line("Photo ingest path", settings.photo_ingest_project_path),
        ]
        return "\n".join(lines)

    async def _build_service_status(self) -> str:
        """Render current service-level adapter results."""
        bluefolder = await self.bot.container.bluefolder_service.get_job_summary("SR-100")
        dispatch = await self.bot.container.dispatch_service.adapter.get_job("SR-100")
        parts = await self.bot.container.parts_cannon_service.adapter.get_part_status("SR-100")
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
            f"Photo ingest: `{photo.get('status', 'unknown')}`",
            f"Photo ingest source: `{photo.get('source', 'unknown')}`",
            f"Notifications: `{notifications.mode}` via `{notifications.transport}`",
            f"Notification notices sent: `{notifications.notice_count}`",
            f"Last notification topic: `{notifications.last_topic or 'none'}`",
        ]
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

    def _build_operator_mappings(self) -> str:
        """Render the current merged operator mapping set."""
        records = self.bot.container.operator_directory_service.mapping_records()
        if not records:
            return "Operator Mappings\nNo operator mappings are currently configured."

        lines = ["Operator Mappings"]
        for record in records:
            lines.append(
                f"Discord user `{record.discord_user_id}` -> BlueFolder user `{record.bluefolder_user_id}`"
            )
        return "\n".join(lines)

    def _build_export_operator_mappings(self) -> str:
        """Persist current mappings to disk and report the result."""
        path = self.bot.container.operator_directory_service.export_mappings()
        if path is None:
            return "Operator mapping export is not configured. Set OPS_HUB_OPERATOR_MAPPING_FILE first."
        return f"Exported operator mappings to `{path}`."

    def _build_reload_operator_mappings(self) -> str:
        """Reload file-backed mappings and report the result."""
        mappings = self.bot.container.operator_directory_service.reload_mappings()
        return f"Reloaded `{len(mappings)}` operator mappings."

    def _build_set_operator_mapping(self, discord_user_id: int, bluefolder_user_id: int) -> str:
        """Create or update an operator mapping."""
        self.bot.container.operator_directory_service.set_mapping(
            discord_user_id=discord_user_id,
            bluefolder_user_id=bluefolder_user_id,
        )
        return f"Mapped Discord user `{discord_user_id}` to BlueFolder user `{bluefolder_user_id}`."

    def _build_remove_operator_mapping(self, discord_user_id: int) -> str:
        """Remove an operator mapping."""
        removed = self.bot.container.operator_directory_service.remove_mapping(discord_user_id=discord_user_id)
        if removed:
            return f"Removed operator mapping for Discord user `{discord_user_id}`."
        return f"No operator mapping existed for Discord user `{discord_user_id}`."

    def _build_command_access(self) -> str:
        """Render the current command access model."""
        return "\n".join(
            [
                "Command Access",
                "`/ops_status`, `/config_check`, `/service_status`, `/recent_notices`, `/operator_mappings`, `/export_operator_mappings`, `/reload_operator_mappings`, `/set_operator_mapping`, `/remove_operator_mapping`, `/command_access`: admin only",
                "`/job`, `/assignments`: technicians, dispatchers, admins",
                "`/part_request`, `/my_part_requests`: technicians, parts, admins",
                "`/part`, `/part_requests`, `/part_update`: parts, admins",
                "`/ping`: open to anyone who can invoke the bot",
            ]
        )

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
        if user_id is None:
            return False
        identity = self.bot.container.operator_directory_service.resolve_identity(
            user_id=user_id,
            role_ids=role_ids,
        )
        return identity.is_admin


async def setup(bot: OpsHubBot) -> None:
    """Load the admin cog."""
    await bot.add_cog(AdminCog(bot))
