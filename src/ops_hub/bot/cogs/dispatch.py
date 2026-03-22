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
            technician_bluefolder_user_id=identity.bluefolder_user_id,
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
            technician_bluefolder_user_id=identity.bluefolder_user_id,
            target_bluefolder_user_id=bluefolder_user_id,
            requester_is_admin=identity.is_admin,
        )
        result = await self.bot.container.dispatch_service.lookup_job(request)
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(name="dispatch_board", description="Show a board summary across all mapped technicians.")
    async def dispatch_board(self, interaction: discord.Interaction) -> None:
        """Dispatcher-focused board summary using current technician mappings."""
        mappings = self.bot.container.technician_directory_service.mapping_records()
        result = await self.bot.container.dispatch_service.lookup_dispatch_board(mappings)
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(name="dispatch_attention", description="Show mapped jobs that look actionable for dispatch right now.")
    async def dispatch_attention(self, interaction: discord.Interaction) -> None:
        """Dispatcher-focused triage view for parts-related attention states."""
        mappings = self.bot.container.technician_directory_service.mapping_records()
        await interaction.response.defer(ephemeral=True)
        result = await self.bot.container.dispatch_service.lookup_dispatch_attention(mappings)
        await interaction.followup.send(result.message, ephemeral=True)

    def _resolve_identity(self, interaction: discord.Interaction):
        """Resolve the invoking Discord user into an Ops Hub dispatcher/admin identity."""
        user_roles = getattr(interaction.user, "roles", None)
        role_ids = {getattr(role, "id", None) for role in user_roles or [] if getattr(role, "id", None) is not None}
        return self.bot.container.technician_directory_service.resolve_identity(
            user_id=interaction.user.id,
            role_ids=role_ids,
        )


async def setup(bot: OpsHubBot) -> None:
    """Load the dispatch cog."""
    await bot.add_cog(DispatchCog(bot))
