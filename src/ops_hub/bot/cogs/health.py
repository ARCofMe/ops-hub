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


async def setup(bot: OpsHubBot) -> None:
    """Load the health cog."""
    await bot.add_cog(HealthCog(bot))

