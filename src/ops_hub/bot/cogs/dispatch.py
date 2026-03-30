"""Dispatcher-facing slash commands."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ops_hub.bot.client import OpsHubBot
from ops_hub.models.requests import JobLookupRequest, TechnicianMappingRecord


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
        await self._send_result(interaction, result.message)

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
        await self._send_result(interaction, result.message)

    @app_commands.command(name="dispatch_board", description="Show a board summary across all mapped technicians.")
    async def dispatch_board(self, interaction: discord.Interaction) -> None:
        """Dispatcher-focused board summary using current technician mappings."""
        mappings = await self._technician_dispatch_mappings(interaction)
        result = await self.bot.container.dispatch_service.lookup_dispatch_board(mappings)
        await self._send_result(interaction, result.message)

    @app_commands.command(name="dispatch_attention", description="Show mapped jobs that look actionable for dispatch right now.")
    @app_commands.describe(
        stage="Optional stage filter: issue_reported, part_received, part_ready, or quote_needed.",
        age="Optional age filter: fresh, warm, stale, or urgent.",
        bluefolder_user_id="Optional BlueFolder technician user id to narrow the view.",
        owner_discord_user_id="Optional Discord technician user id to narrow by owner.",
    )
    async def dispatch_attention(
        self,
        interaction: discord.Interaction,
        stage: str | None = None,
        age: str | None = None,
        bluefolder_user_id: int | None = None,
        owner_discord_user_id: int | None = None,
    ) -> None:
        """Dispatcher-focused triage view for parts-related attention states."""
        mappings = await self._technician_dispatch_mappings(interaction)
        await interaction.response.defer(ephemeral=True)
        result = await self.bot.container.dispatch_service.lookup_dispatch_attention(
            mappings,
            stage_filter=stage,
            technician_bluefolder_user_id=bluefolder_user_id,
            age_bucket=age,
            owner_discord_user_id=owner_discord_user_id,
        )
        await self._send_deferred_result(interaction, result.message)

    @app_commands.command(name="attention_ack", description="Acknowledge one workflow attention item.")
    @app_commands.describe(
        sr_id="Service request id to acknowledge.",
        stage="Optional stage when an SR has more than one attention item.",
    )
    async def attention_ack(
        self,
        interaction: discord.Interaction,
        sr_id: int,
        stage: str | None = None,
    ) -> None:
        """Acknowledge one dispatch attention item."""
        result = await self.bot.container.dispatch_service.acknowledge_dispatch_attention(
            sr_id=sr_id,
            stage=stage,
            actor_user_id=interaction.user.id,
        )
        await self._send_deferred_result(interaction, result.message)

    @app_commands.command(name="attention_snooze", description="Snooze one workflow attention item for a few hours.")
    @app_commands.describe(
        sr_id="Service request id to snooze.",
        hours="How long to snooze the item.",
        stage="Optional stage when an SR has more than one attention item.",
    )
    async def attention_snooze(
        self,
        interaction: discord.Interaction,
        sr_id: int,
        hours: app_commands.Range[int, 1, 72],
        stage: str | None = None,
    ) -> None:
        """Snooze one dispatch attention item."""
        result = await self.bot.container.dispatch_service.snooze_dispatch_attention(
            sr_id=sr_id,
            stage=stage,
            hours=int(hours),
            actor_user_id=interaction.user.id,
        )
        await self._send_deferred_result(interaction, result.message)

    @app_commands.command(name="attention_assign", description="Assign a follow-up owner to one workflow attention item.")
    @app_commands.describe(
        sr_id="Service request id to assign.",
        owner_discord_user_id="Discord user id that should own the follow-up.",
        stage="Optional stage when an SR has more than one attention item.",
    )
    async def attention_assign(
        self,
        interaction: discord.Interaction,
        sr_id: int,
        owner_discord_user_id: int,
        stage: str | None = None,
    ) -> None:
        """Assign a follow-up owner on one dispatch attention item."""
        result = await self.bot.container.dispatch_service.assign_dispatch_attention_owner(
            sr_id=sr_id,
            stage=stage,
            assigned_owner_discord_user_id=owner_discord_user_id,
            actor_user_id=interaction.user.id,
        )
        await self._send_deferred_result(interaction, result.message)

    @app_commands.command(name="attention_clear_owner", description="Clear the explicit follow-up owner on one workflow attention item.")
    @app_commands.describe(
        sr_id="Service request id to update.",
        stage="Optional stage when an SR has more than one attention item.",
    )
    async def attention_clear_owner(
        self,
        interaction: discord.Interaction,
        sr_id: int,
        stage: str | None = None,
    ) -> None:
        """Clear a follow-up owner on one dispatch attention item."""
        result = await self.bot.container.dispatch_service.clear_dispatch_attention_owner(
            sr_id=sr_id,
            stage=stage,
            actor_user_id=interaction.user.id,
        )
        await self._send_deferred_result(interaction, result.message)

    @app_commands.command(name="attention_unsnooze", description="Remove the current snooze from one workflow attention item.")
    @app_commands.describe(
        sr_id="Service request id to unsnooze.",
        stage="Optional stage when an SR has more than one attention item.",
    )
    async def attention_unsnooze(
        self,
        interaction: discord.Interaction,
        sr_id: int,
        stage: str | None = None,
    ) -> None:
        """Remove a snooze from one dispatch attention item."""
        result = await self.bot.container.dispatch_service.unsnooze_dispatch_attention(
            sr_id=sr_id,
            stage=stage,
            actor_user_id=interaction.user.id,
        )
        await self._send_deferred_result(interaction, result.message)

    @app_commands.command(name="attention_reopen", description="Return one workflow attention item to open state.")
    @app_commands.describe(
        sr_id="Service request id to reopen.",
        stage="Optional stage when an SR has more than one attention item.",
    )
    async def attention_reopen(
        self,
        interaction: discord.Interaction,
        sr_id: int,
        stage: str | None = None,
    ) -> None:
        """Reopen one dispatch attention item."""
        result = await self.bot.container.dispatch_service.reopen_dispatch_attention(
            sr_id=sr_id,
            stage=stage,
            actor_user_id=interaction.user.id,
        )
        await self._send_deferred_result(interaction, result.message)

    @app_commands.command(name="attention_history", description="Show recent workflow history for one attention item.")
    @app_commands.describe(
        sr_id="Service request id to inspect.",
        stage="Optional stage when an SR has more than one attention item.",
    )
    async def attention_history(
        self,
        interaction: discord.Interaction,
        sr_id: int,
        stage: str | None = None,
    ) -> None:
        """Show recent workflow history for one dispatch attention item."""
        result = await self.bot.container.dispatch_service.describe_dispatch_attention_history(
            sr_id=sr_id,
            stage=stage,
        )
        await self._send_deferred_result(interaction, result.message)

    @app_commands.command(name="dispatch_next", description="Show the recommended next dispatch action for a specific SR.")
    async def dispatch_next(self, interaction: discord.Interaction, sr_id: int) -> None:
        """Dispatcher-focused next-action summary for a service request."""
        result = await self.bot.container.workflow_state_service.describe_parts_case(sr_id)
        await self._send_deferred_result(interaction, result.message)

    @app_commands.command(name="photo_compliance_board", description="Show current jobs that still need required photos.")
    @app_commands.describe(actionable_only="Only show jobs that are in a photo-required status and still missing photos.")
    async def photo_compliance_board(
        self,
        interaction: discord.Interaction,
        actionable_only: bool = True,
    ) -> None:
        """Dispatcher-facing board for current photo compliance gaps."""
        mappings = await self._technician_dispatch_mappings(interaction)
        await interaction.response.defer(ephemeral=True)
        result = await self.bot.container.photo_ingest_service.build_photo_compliance_board(
            mappings,
            actionable_only=actionable_only,
        )
        await self._send_deferred_result(interaction, result.message)

    @app_commands.command(name="dispatch_heatmap", description="Show a mini-map of current assignment hotspots.")
    @app_commands.describe(bluefolder_user_id="Optional BlueFolder technician user id to narrow the heatmap.")
    async def dispatch_heatmap(
        self,
        interaction: discord.Interaction,
        bluefolder_user_id: int | None = None,
    ) -> None:
        """Dispatcher-facing mini heatmap of current mapped assignments."""
        mappings = await self._technician_dispatch_mappings(interaction)
        await interaction.response.defer(ephemeral=True)
        result = await self.bot.container.dispatch_service.lookup_assignment_heatmap(
            mappings,
            technician_bluefolder_user_id=bluefolder_user_id,
        )
        embed = None
        if result.image_url:
            embed = discord.Embed(title="Assignment Heatmap")
            embed.set_image(url=result.image_url)
        await self._send_deferred_result(interaction, result.message, embed=embed)

    async def _send_result(self, interaction: discord.Interaction, message: str) -> None:
        """Send a standard ephemeral dispatcher response."""
        await interaction.response.send_message(message, ephemeral=True)

    async def _send_deferred_result(
        self,
        interaction: discord.Interaction,
        message: str,
        *,
        embed: discord.Embed | None = None,
    ) -> None:
        """Send a standard deferred ephemeral dispatcher response."""
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(message, embed=embed, ephemeral=True)

    def _resolve_identity(self, interaction: discord.Interaction):
        """Resolve the invoking Discord user into an Ops Hub dispatcher/admin identity."""
        user_roles = getattr(interaction.user, "roles", None)
        role_ids = {getattr(role, "id", None) for role in user_roles or [] if getattr(role, "id", None) is not None}
        guild_permissions = getattr(interaction.user, "guild_permissions", None)
        has_administrator_permission = bool(getattr(guild_permissions, "administrator", False))
        guild = getattr(interaction, "guild", None)
        is_guild_owner = bool(guild is not None and getattr(guild, "owner_id", None) == interaction.user.id)
        return self.bot.container.technician_directory_service.resolve_identity(
            user_id=interaction.user.id,
            role_ids=role_ids,
            has_administrator_permission=has_administrator_permission,
            is_guild_owner=is_guild_owner,
        )

    async def _technician_dispatch_mappings(
        self,
        interaction: discord.Interaction,
    ) -> list[TechnicianMappingRecord]:
        """Return technician mappings scoped to actual Discord technician members when possible."""
        directory = self.bot.container.technician_directory_service
        guild = interaction.guild
        if guild is None:
            return directory.mapping_records()

        members = list(getattr(guild, "members", []) or [])
        if not members and hasattr(guild, "fetch_members"):
            fetched_members = []
            async for member in guild.fetch_members(limit=None):
                fetched_members.append(member)
            members = fetched_members

        if not members:
            return directory.mapping_records()

        technician_role_ids = set(self.bot.settings.technician_role_ids)
        technician_user_ids = set(self.bot.settings.technician_user_ids)
        mappings = directory.mappings()
        technician_member_ids: set[int] = set()
        for member in members:
            role_ids = {
                getattr(role, "id", None)
                for role in getattr(member, "roles", []) or []
                if getattr(role, "id", None) is not None
            }
            is_technician = member.id in technician_user_ids or bool(role_ids & technician_role_ids)
            if not is_technician:
                continue
            technician_member_ids.add(member.id)

        bluefolder_to_discord: dict[int, list[int]] = {}
        for discord_user_id, bluefolder_user_id in mappings.items():
            bluefolder_to_discord.setdefault(bluefolder_user_id, []).append(discord_user_id)

        records: list[TechnicianMappingRecord] = []
        for bluefolder_user_id, discord_user_ids in sorted(bluefolder_to_discord.items()):
            chosen_discord_user_id = next(
                (discord_user_id for discord_user_id in sorted(discord_user_ids) if discord_user_id in technician_member_ids),
                None,
            )
            if chosen_discord_user_id is None:
                continue
            records.append(
                TechnicianMappingRecord(
                    discord_user_id=chosen_discord_user_id,
                    bluefolder_user_id=bluefolder_user_id,
                )
            )
        return records


async def setup(bot: OpsHubBot) -> None:
    """Load the dispatch cog."""
    await bot.add_cog(DispatchCog(bot))
