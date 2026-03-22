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

    async def cog_app_command_check(self, interaction: discord.Interaction) -> bool:
        """Restrict the operations surface to recognized technicians, parts, dispatchers, or admins."""
        identity = self._resolve_identity(interaction)
        if identity.is_operator or identity.is_parts or identity.is_dispatcher:
            return True
        raise app_commands.CheckFailure("You do not have permission to use this command.")

    @app_commands.command(name="job", description="Look up a job or service request in Ops Hub.")
    @app_commands.describe(reference="Optional job reference or SR id. Leave blank to see current assignments.")
    async def job(self, interaction: discord.Interaction, reference: str | None = None) -> None:
        """Job lookup command."""
        identity = self._resolve_identity(interaction)
        if not (identity.is_operator or identity.is_dispatcher):
            raise app_commands.CheckFailure("You do not have permission to use this command.")
        request = JobLookupRequest(
            reference=reference,
            requested_by_user_id=interaction.user.id,
            operator_bluefolder_user_id=identity.bluefolder_user_id,
            requester_is_admin=identity.is_admin,
        )
        result = await self.bot.container.dispatch_service.lookup_job(request)
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(name="part", description="Look up or start a parts workflow action.")
    @app_commands.describe(reference="Part number, SR id, request id, or lookup token.")
    async def part(self, interaction: discord.Interaction, reference: str) -> None:
        """Parts workflow command."""
        identity = self._resolve_identity(interaction)
        if not identity.is_parts:
            raise app_commands.CheckFailure("You do not have permission to use this command.")
        request = PartLookupRequest(
            reference=reference,
            requested_by_user_id=interaction.user.id,
            operator_bluefolder_user_id=identity.bluefolder_user_id,
            requester_is_admin=identity.is_admin,
        )
        result = await self.bot.container.parts_cannon_service.lookup_part(request)
        await interaction.response.send_message(result.message, ephemeral=True)

    def _resolve_identity(self, interaction: discord.Interaction):
        """Resolve the invoking Discord user into an Ops Hub operator/admin identity."""
        user_roles = getattr(interaction.user, "roles", None)
        role_ids = {getattr(role, "id", None) for role in user_roles or [] if getattr(role, "id", None) is not None}
        return self.bot.container.operator_directory_service.resolve_identity(
            user_id=interaction.user.id,
            role_ids=role_ids,
        )


async def setup(bot: OpsHubBot) -> None:
    """Load the operations cog."""
    await bot.add_cog(OperationsCog(bot))
