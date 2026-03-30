"""Health and diagnostics commands."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ops_hub.bot.client import OpsHubBot


class HealthCog(commands.Cog):
    """Basic health commands for the bot runtime."""

    OPEN_LINES = ("`/ping`, `/help`",)
    TECHNICIAN_LINES = (
        "`/job`, `/assignments`, `/route_map`",
        "`/customer`, `/eta`, `/enroute`, `/start`",
        "`/no_answer`, `/not_home`, `/reschedule_needed`, `/note`",
        "`/mdlsn`, `/photo_archive`, `/photo_status`",
        "`/part_request`, `/my_part_requests`",
        "`/missing_part`, `/damaged_part`",
        "`/parts_brief`, `/parts_notes`",
    )
    DISPATCH_LINES = (
        "`/job`, `/assignments`, `/route_map`, `/customer`",
        "`/tech_assignments`, `/tech_job`",
        "`/dispatch_board`, `/dispatch_attention`, `/dispatch_next`, `/dispatch_heatmap`, `/photo_compliance_board`",
        "`/attention_ack`, `/attention_snooze`, `/attention_assign`, `/attention_clear_owner`",
        "`/attention_unsnooze`, `/attention_reopen`, `/attention_history`",
        "`/parts_brief`, `/parts_notes`, `/photo_status`, `/photo_reminder_check`",
    )
    PARTS_LINES = (
        "`/part`, `/part_requests`, `/part_request_detail`, `/part_update`",
        "`/part_claim`, `/part_unclaim`, `/part_sync`, `/part_reconcile`",
        "`/parts_brief`, `/parts_notes`, `/photo_status`",
        "`/part_ordered`, `/part_eta`, `/part_tracking`, `/part_received`, `/part_ready`",
    )
    ADMIN_LINES = (
        "`/ops_status`, `/config_check`, `/service_status`, `/recent_notices`",
        "`/policy_status`, `/policy_preview`, `/policy_run_now`",
        "`/bluefolder_techs`, `/export_member_map`, `/suggest_tech_map`, `/lookup_member`",
        "`/technician_mappings`, `/export_technician_mappings`, `/import_technician_mappings`, `/reload_technician_mappings`",
        "`/set_technician_mapping`, `/remove_technician_mapping`, `/command_access`",
        "`/photo_features`, `/set_photo_feature`, `/clear_photo_feature`",
    )

    def __init__(self, bot: OpsHubBot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Check whether Ops Hub is responsive.")
    async def ping(self, interaction: discord.Interaction) -> None:
        """Simple liveness command."""
        await interaction.response.send_message("pong", ephemeral=True)

    @app_commands.command(name="help", description="Show the current Ops Hub command guide.")
    async def help(self, interaction: discord.Interaction) -> None:
        """Render a concise command guide grouped by business role."""
        await interaction.response.send_message(self._build_help_text(interaction), ephemeral=True)

    def _build_help_text(self, interaction: discord.Interaction | None = None) -> str:
        """Return a role-aware command guide."""
        lines = [
            "**Ops Hub Command Guide**",
            "",
            "**Open**",
            *self.OPEN_LINES,
        ]
        identity = self._resolve_identity(interaction)
        for header, visible, command_lines in (
            ("Technician", identity.is_technician, self.TECHNICIAN_LINES),
            ("Dispatch", identity.is_dispatcher, self.DISPATCH_LINES),
            ("Parts", identity.is_parts, self.PARTS_LINES),
            ("Admin", identity.is_admin, self.ADMIN_LINES),
        ):
            if not visible:
                continue
            lines.extend(["", f"**{header}**", *command_lines])
        if not any((identity.is_technician, identity.is_dispatcher, identity.is_parts, identity.is_admin)):
            lines.extend(
                [
                    "",
                    "No role-specific commands are currently available for your account.",
                    "If you expected more access, ask an admin to check your Ops Hub roles and technician mapping.",
                ]
            )
        return "\n".join(lines)

    def _resolve_identity(self, interaction: discord.Interaction | None):
        """Resolve the invoking Discord user into an Ops Hub identity for help visibility."""
        if interaction is None:
            return self.bot.container.technician_directory_service.resolve_identity(user_id=0, role_ids=set())
        user = getattr(interaction, "user", None)
        user_id = getattr(user, "id", 0)
        user_roles = getattr(user, "roles", None)
        role_ids = {getattr(role, "id", None) for role in user_roles or [] if getattr(role, "id", None) is not None}
        return self.bot.container.technician_directory_service.resolve_identity(
            user_id=user_id,
            role_ids=role_ids,
        )


async def setup(bot: OpsHubBot) -> None:
    """Load the health cog."""
    await bot.add_cog(HealthCog(bot))
