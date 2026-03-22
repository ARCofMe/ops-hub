"""Dispatcher-facing slash commands."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ops_hub.bot.client import OpsHubBot
from ops_hub.models.requests import JobLookupRequest


class DispatchCog(commands.Cog):
    """Dispatcher-focused command surface."""

    def __init__(self, bot: OpsHubBot) -> None:
        self.bot = bot

    async def cog_app_command_check(self, interaction: discord.Interaction) -> bool:
        """Restrict dispatcher commands to dispatchers and admins."""
        identity = self._resolve_identity(interaction)
        if identity.is_dispatcher:
            return True
        raise app_commands.CheckFailure("You do not have permission to use this command.")

    @app_commands.command(name="tech_assignments", description="Show current assignments for a specific BlueFolder user.")
    @app_commands.describe(bluefolder_user_id="BlueFolder user id to inspect.")
    async def tech_assignments(self, interaction: discord.Interaction, bluefolder_user_id: int) -> None:
        """Dispatcher-focused assignment lookup for a specific tech."""
        identity = self._resolve_identity(interaction)
        request = JobLookupRequest(
            reference=None,
            requested_by_user_id=interaction.user.id,
            operator_bluefolder_user_id=identity.bluefolder_user_id,
            target_bluefolder_user_id=bluefolder_user_id,
            requester_is_admin=identity.is_admin,
        )
        result = await self.bot.container.dispatch_service.lookup_assignments(request)
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(name="tech_job", description="Look up a job with explicit tech dispatch context.")
    @app_commands.describe(
        bluefolder_user_id="BlueFolder user id to inspect.",
        reference="Job reference or SR id.",
    )
    async def tech_job(
        self,
        interaction: discord.Interaction,
        bluefolder_user_id: int,
        reference: str,
    ) -> None:
        """Dispatcher-focused job lookup for a specific tech."""
        identity = self._resolve_identity(interaction)
        request = JobLookupRequest(
            reference=reference,
            requested_by_user_id=interaction.user.id,
            operator_bluefolder_user_id=identity.bluefolder_user_id,
            target_bluefolder_user_id=bluefolder_user_id,
            requester_is_admin=identity.is_admin,
        )
        result = await self.bot.container.dispatch_service.lookup_job(request)
        await interaction.response.send_message(result.message, ephemeral=True)

    def _resolve_identity(self, interaction: discord.Interaction):
        """Resolve the invoking Discord user into an Ops Hub dispatcher/admin identity."""
        user_roles = getattr(interaction.user, "roles", None)
        role_ids = {getattr(role, "id", None) for role in user_roles or [] if getattr(role, "id", None) is not None}
        return self.bot.container.operator_directory_service.resolve_identity(
            user_id=interaction.user.id,
            role_ids=role_ids,
        )


async def setup(bot: OpsHubBot) -> None:
    """Load the dispatch cog."""
    await bot.add_cog(DispatchCog(bot))
