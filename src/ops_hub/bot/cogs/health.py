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

    @app_commands.command(name="ops_help", description="Show the current Ops Hub command guide.")
    async def ops_help(self, interaction: discord.Interaction) -> None:
        """Render a concise command guide grouped by business role."""
        await interaction.response.send_message(self._build_help_text(), ephemeral=True)

    def _build_help_text(self) -> str:
        """Return the current public command guide."""
        return "\n".join(
            [
                "Ops Hub Command Guide",
                "Open access: `/ping`, `/ops_help`",
                "Technician: `/job`, `/assignments`, `/part_request`, `/my_part_requests`",
                "Dispatch: `/job`, `/assignments`, `/tech_assignments`, `/tech_job`",
                "Parts: `/part`, `/part_requests`, `/part_request_detail`, `/part_update`, `/part_claim`, `/part_unclaim`, `/part_sync`",
                "Admin: `/ops_status`, `/config_check`, `/service_status`, `/recent_notices`, `/operator_mappings`, `/export_operator_mappings`, `/reload_operator_mappings`, `/set_operator_mapping`, `/remove_operator_mapping`, `/command_access`",
                "Business term note: `operator` in config currently maps to Technician access.",
            ]
        )


async def setup(bot: OpsHubBot) -> None:
    """Load the health cog."""
    await bot.add_cog(HealthCog(bot))
