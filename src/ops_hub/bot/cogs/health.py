"""Health and diagnostics commands."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ops_hub.bot.client import OpsHubBot


class HealthCog(commands.Cog):
    """Basic health commands for the bot runtime."""

    def __init__(self, bot: OpsHubBot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Check whether Ops Hub is responsive.")
    async def ping(self, interaction: discord.Interaction) -> None:
        """Simple liveness command."""
        await interaction.response.send_message("pong", ephemeral=True)

    @app_commands.command(name="help", description="Show the current Ops Hub command guide.")
    async def help(self, interaction: discord.Interaction) -> None:
        """Render a concise command guide grouped by business role."""
        await interaction.response.send_message(self._build_help_text(), ephemeral=True)

    def _build_help_text(self) -> str:
        """Return the current public command guide."""
        return "\n".join(
            [
                "**Ops Hub Command Guide**",
                "",
                "**Open**",
                "`/ping`, `/help`",
                "",
                "**Technician**",
                "`/job`, `/assignments`, `/route_map`",
                "`/customer`, `/eta`, `/enroute`, `/start`",
                "`/no_answer`, `/not_home`, `/reschedule_needed`, `/note`",
                "`/mdlsn`, `/photo_archive`, `/photo_status`",
                "`/part_request`, `/my_part_requests`",
                "`/missing_part`, `/damaged_part`",
                "`/parts_brief`, `/parts_notes`",
                "",
                "**Dispatch**",
                "`/job`, `/assignments`, `/route_map`, `/customer`",
                "`/tech_assignments`, `/tech_job`",
                "`/dispatch_board`, `/dispatch_attention`, `/dispatch_next`, `/dispatch_heatmap`, `/photo_compliance_board`",
                "`/parts_brief`, `/parts_notes`, `/photo_status`, `/photo_reminder_check`",
                "",
                "**Parts**",
                "`/part`, `/part_requests`, `/part_request_detail`, `/part_update`",
                "`/part_claim`, `/part_unclaim`, `/part_sync`, `/part_reconcile`",
                "`/parts_brief`, `/parts_notes`, `/photo_status`",
                "`/part_ordered`, `/part_eta`, `/part_tracking`, `/part_received`, `/part_ready`",
                "",
                "**Admin**",
                "`/ops_status`, `/config_check`, `/service_status`, `/recent_notices`",
                "`/bluefolder_techs`, `/export_member_map`, `/suggest_tech_map`, `/lookup_member`",
                "`/technician_mappings`, `/export_technician_mappings`, `/import_technician_mappings`, `/reload_technician_mappings`",
                "`/set_technician_mapping`, `/remove_technician_mapping`, `/command_access`",
                "`/photo_features`, `/set_photo_feature`, `/clear_photo_feature`",
            ]
        )


async def setup(bot: OpsHubBot) -> None:
    """Load the health cog."""
    await bot.add_cog(HealthCog(bot))
