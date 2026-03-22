"""Operations-facing slash commands."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ops_hub.bot.client import OpsHubBot
from ops_hub.models.requests import JobLookupRequest, PartLookupRequest, PartRequestCreate, PartRequestUpdate


class OperationsCog(commands.Cog):
    """Primary operations commands scaffold."""

    def __init__(self, bot: OpsHubBot) -> None:
        self.bot = bot

    async def cog_app_command_check(self, interaction: discord.Interaction) -> bool:
        """Restrict the operations surface to recognized technicians, parts, dispatchers, or admins."""
        identity = self._resolve_identity(interaction)
        if identity.is_admin or identity.is_operator or identity.is_parts or identity.is_dispatcher:
            return True
        raise app_commands.CheckFailure("You do not have permission to use this command.")

    @app_commands.command(name="job", description="Look up a job or service request in Ops Hub.")
    @app_commands.describe(reference="Optional job reference or SR id. Leave blank to see current assignments.")
    async def job(self, interaction: discord.Interaction, reference: str | None = None) -> None:
        """Job lookup command."""
        identity = self._resolve_identity(interaction)
        if not self._can_use_job_commands(identity):
            raise app_commands.CheckFailure("You do not have permission to use this command.")
        request = JobLookupRequest(
            reference=reference,
            requested_by_user_id=interaction.user.id,
            operator_bluefolder_user_id=identity.bluefolder_user_id,
            requester_is_admin=identity.is_admin,
        )
        result = await self.bot.container.dispatch_service.lookup_job(request)
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(name="assignments", description="Show current assignments for a mapped or specified BlueFolder user.")
    @app_commands.describe(
        bluefolder_user_id="Optional BlueFolder user id. Dispatch/Admin can override; technicians use their mapping by default."
    )
    async def assignments(
        self,
        interaction: discord.Interaction,
        bluefolder_user_id: int | None = None,
    ) -> None:
        """Current assignment summary command."""
        identity = self._resolve_identity(interaction)
        if not self._can_use_job_commands(identity):
            raise app_commands.CheckFailure("You do not have permission to use this command.")
        if bluefolder_user_id is not None and not (identity.is_dispatcher or identity.is_admin):
            raise app_commands.CheckFailure("Only dispatch or admin can request another user's assignments.")
        request = JobLookupRequest(
            reference=None,
            requested_by_user_id=interaction.user.id,
            operator_bluefolder_user_id=identity.bluefolder_user_id,
            target_bluefolder_user_id=bluefolder_user_id,
            requester_is_admin=identity.is_admin,
        )
        result = await self.bot.container.dispatch_service.lookup_assignments(request)
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(name="part", description="Look up or start a parts workflow action.")
    @app_commands.describe(reference="Part number, SR id, request id, or lookup token.")
    async def part(self, interaction: discord.Interaction, reference: str) -> None:
        """Parts workflow command."""
        identity = self._resolve_identity(interaction)
        if not self._can_use_parts_commands(identity):
            raise app_commands.CheckFailure("You do not have permission to use this command.")
        request = PartLookupRequest(
            reference=reference,
            requested_by_user_id=interaction.user.id,
            operator_bluefolder_user_id=identity.bluefolder_user_id,
            requester_is_admin=identity.is_admin,
        )
        result = await self.bot.container.parts_cannon_service.lookup_part(request)
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(name="part_request", description="Create a new tracked parts request.")
    @app_commands.describe(
        reference="Service request id, job reference, or other parts reference.",
        description="Short description of the needed part or issue.",
    )
    async def part_request(self, interaction: discord.Interaction, reference: str, description: str) -> None:
        """Create a tracked parts request."""
        identity = self._resolve_identity(interaction)
        if not self._can_use_parts_commands(identity):
            raise app_commands.CheckFailure("You do not have permission to use this command.")
        result = await self.bot.container.parts_cannon_service.create_request(
            PartRequestCreate(
                reference=reference,
                description=description,
                requested_by_user_id=interaction.user.id,
                operator_bluefolder_user_id=identity.bluefolder_user_id,
                requester_is_admin=identity.is_admin,
            )
        )
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(name="part_requests", description="List tracked parts requests.")
    @app_commands.describe(status="Optional status filter: requested, ordered, received, resolved, cancelled.")
    async def part_requests(self, interaction: discord.Interaction, status: str | None = None) -> None:
        """List tracked parts requests, optionally filtered by status."""
        identity = self._resolve_identity(interaction)
        if not self._can_use_parts_commands(identity):
            raise app_commands.CheckFailure("You do not have permission to use this command.")
        result = await self.bot.container.parts_cannon_service.list_requests(status=status)
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(name="part_update", description="Update the status of a tracked parts request.")
    @app_commands.describe(
        request_id="Tracked parts request id.",
        status="New status: requested, ordered, received, resolved, cancelled.",
    )
    async def part_update(self, interaction: discord.Interaction, request_id: int, status: str) -> None:
        """Update a tracked parts request status."""
        identity = self._resolve_identity(interaction)
        if not self._can_use_parts_commands(identity):
            raise app_commands.CheckFailure("You do not have permission to use this command.")
        result = await self.bot.container.parts_cannon_service.update_request(
            PartRequestUpdate(
                request_id=request_id,
                status=status,
                updated_by_user_id=interaction.user.id,
            )
        )
        await interaction.response.send_message(result.message, ephemeral=True)

    def _resolve_identity(self, interaction: discord.Interaction):
        """Resolve the invoking Discord user into an Ops Hub operator/admin identity."""
        user_roles = getattr(interaction.user, "roles", None)
        role_ids = {getattr(role, "id", None) for role in user_roles or [] if getattr(role, "id", None) is not None}
        return self.bot.container.operator_directory_service.resolve_identity(
            user_id=interaction.user.id,
            role_ids=role_ids,
        )

    def _can_use_job_commands(self, identity) -> bool:
        """Return whether the user can access job and assignments commands."""
        return identity.is_admin or identity.is_operator or identity.is_dispatcher

    def _can_use_parts_commands(self, identity) -> bool:
        """Return whether the user can access parts workflow commands."""
        return identity.is_admin or identity.is_parts


async def setup(bot: OpsHubBot) -> None:
    """Load the operations cog."""
    await bot.add_cog(OperationsCog(bot))
