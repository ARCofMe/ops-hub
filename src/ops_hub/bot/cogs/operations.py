"""Operations-facing slash commands."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ops_hub.bot.client import OpsHubBot
from ops_hub.models.requests import JobLookupRequest, PartLookupRequest


class OperationsCog(commands.Cog):
    """Primary operations commands scaffold."""

    def __init__(self, bot: OpsHubBot) -> None:
        self.bot = bot

    @app_commands.command(name="job", description="Look up a job or service request in Ops Hub.")
    @app_commands.describe(reference="Job reference, SR id, or other lookup token.")
    async def job(self, interaction: discord.Interaction, reference: str) -> None:
        """Placeholder job lookup command."""
        request = JobLookupRequest(reference=reference, requested_by_user_id=interaction.user.id)
        result = await self.bot.container.dispatch_service.lookup_job(request)
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(name="part", description="Look up or start a parts workflow action.")
    @app_commands.describe(reference="Part number, SR id, request id, or lookup token.")
    async def part(self, interaction: discord.Interaction, reference: str) -> None:
        """Placeholder parts workflow command."""
        request = PartLookupRequest(reference=reference, requested_by_user_id=interaction.user.id)
        result = await self.bot.container.parts_cannon_service.lookup_part(request)
        await interaction.response.send_message(result.message, ephemeral=True)


async def setup(bot: OpsHubBot) -> None:
    """Load the operations cog."""
    await bot.add_cog(OperationsCog(bot))

