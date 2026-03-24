"""Operations-facing slash commands."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ops_hub.bot.client import OpsHubBot
from ops_hub.models.requests import (
    JobLookupRequest,
    PartLookupRequest,
    PartRequestClaim,
    PartRequestCreate,
    PartRequestUpdate,
    PhotoAttachmentPayload,
)


class OperationsCog(commands.Cog):
    """Primary operations commands scaffold."""

    def __init__(self, bot: OpsHubBot) -> None:
        self.bot = bot

    async def cog_app_command_check(self, interaction: discord.Interaction) -> bool:
        """Restrict the operations surface to recognized technicians, parts, dispatchers, or admins."""
        identity = self._resolve_identity(interaction)
        if identity.is_admin or identity.is_technician or identity.is_parts or identity.is_dispatcher:
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
            technician_bluefolder_user_id=identity.bluefolder_user_id,
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
            technician_bluefolder_user_id=identity.bluefolder_user_id,
            target_bluefolder_user_id=bluefolder_user_id,
            requester_is_admin=identity.is_admin,
        )
        result = await self.bot.container.dispatch_service.lookup_assignments(request)
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(name="route_map", description="Show today's route as an inline map preview.")
    @app_commands.describe(
        bluefolder_user_id="Optional BlueFolder user id. Dispatch/Admin can override; technicians use their mapping by default."
    )
    async def route_map(
        self,
        interaction: discord.Interaction,
        bluefolder_user_id: int | None = None,
    ) -> None:
        """Show a route preview map for the current day's assignments."""
        identity = self._resolve_identity(interaction)
        if not self._can_use_job_commands(identity):
            raise app_commands.CheckFailure("You do not have permission to use this command.")
        if bluefolder_user_id is not None and not (identity.is_dispatcher or identity.is_admin):
            raise app_commands.CheckFailure("Only dispatch or admin can request another user's route map.")

        request = JobLookupRequest(
            reference=None,
            requested_by_user_id=interaction.user.id,
            technician_bluefolder_user_id=identity.bluefolder_user_id,
            target_bluefolder_user_id=bluefolder_user_id,
            requester_is_admin=identity.is_admin,
        )
        await interaction.response.defer(ephemeral=True)
        result = await self.bot.container.dispatch_service.lookup_route_map(request)
        embed = None
        if result.image_url:
            embed = discord.Embed(title="Route Preview")
            embed.set_image(url=result.image_url)
        await interaction.followup.send(result.message, embed=embed, ephemeral=True)

    @app_commands.command(name="mdlsn", description="Attach a compressed model/serial photo to a BlueFolder service request.")
    async def mdlsn(
        self,
        interaction: discord.Interaction,
        sr_id: int,
        image: discord.Attachment,
    ) -> None:
        """Attach a model/serial photo to a service request."""
        identity = self._resolve_identity(interaction)
        if not self._can_upload_sr_photo(identity):
            raise app_commands.CheckFailure("You do not have permission to use this command.")
        payload = await self._attachment_payload(image)
        result = await self.bot.container.photo_ingest_service.attach_model_serial_photo(
            sr_id,
            photo=payload,
            requested_by_user_id=interaction.user.id,
        )
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(name="photo_archive", description="Email one or more compressed job photos to the archive mailbox.")
    @app_commands.describe(
        image_1="First required photo.",
        image_2="Optional second photo.",
        image_3="Optional third photo.",
        image_4="Optional fourth photo.",
    )
    async def photo_archive(
        self,
        interaction: discord.Interaction,
        sr_id: int,
        image_1: discord.Attachment,
        image_2: discord.Attachment | None = None,
        image_3: discord.Attachment | None = None,
        image_4: discord.Attachment | None = None,
    ) -> None:
        """Archive one or more job photos through the configured email handoff."""
        identity = self._resolve_identity(interaction)
        if not self._can_upload_sr_photo(identity):
            raise app_commands.CheckFailure("You do not have permission to use this command.")
        attachments = [image for image in [image_1, image_2, image_3, image_4] if image is not None]
        payloads = [await self._attachment_payload(image) for image in attachments]
        summary = await self.bot.container.bluefolder_service.get_job_summary(f"SR-{sr_id}")
        result = await self.bot.container.photo_ingest_service.archive_job_photos(
            sr_id,
            photos=payloads,
            requested_by_user_id=interaction.user.id,
            sr_subject=summary.subject if summary.available else None,
        )
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(name="part", description="Look up or start a parts workflow action.")
    @app_commands.describe(reference="Part number, SR id, request id, or lookup token.")
    async def part(self, interaction: discord.Interaction, reference: str) -> None:
        """Parts workflow command."""
        identity = self._resolve_identity(interaction)
        if not self._can_use_parts_queue(identity):
            raise app_commands.CheckFailure("You do not have permission to use this command.")
        request = PartLookupRequest(
            reference=reference,
            requested_by_user_id=interaction.user.id,
            technician_bluefolder_user_id=identity.bluefolder_user_id,
            requester_is_admin=identity.is_admin,
        )
        result = await self.bot.container.parts_cannon_service.lookup_part(request)
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(name="parts_brief", description="Show a BlueFolder-native parts summary for a service request.")
    async def parts_brief(self, interaction: discord.Interaction, sr_id: int) -> None:
        """Show a compact parts summary based on BlueFolder comments and SR context."""
        identity = self._resolve_identity(interaction)
        if not self._can_view_parts_context(identity):
            raise app_commands.CheckFailure("You do not have permission to use this command.")
        result = await self.bot.container.bluefolder_service.get_parts_brief(sr_id)
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(name="parts_notes", description="Show recent parts-related BlueFolder comments for a service request.")
    async def parts_notes(self, interaction: discord.Interaction, sr_id: int) -> None:
        """Show recent parts-related BlueFolder comments."""
        identity = self._resolve_identity(interaction)
        if not self._can_view_parts_context(identity):
            raise app_commands.CheckFailure("You do not have permission to use this command.")
        result = await self.bot.container.bluefolder_service.get_parts_notes(sr_id)
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(name="missing_part", description="Log a missing-part issue to BlueFolder for a service request.")
    async def missing_part(self, interaction: discord.Interaction, sr_id: int, details: str) -> None:
        """Log a missing-part BlueFolder comment."""
        identity = self._resolve_identity(interaction)
        if not self._can_write_parts_issue(identity):
            raise app_commands.CheckFailure("You do not have permission to use this command.")
        result = await self.bot.container.bluefolder_service.log_parts_issue(
            sr_id,
            issue_type="missing_part",
            details=details,
            requested_by_user_id=interaction.user.id,
        )
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(name="damaged_part", description="Log a damaged-part issue to BlueFolder for a service request.")
    async def damaged_part(self, interaction: discord.Interaction, sr_id: int, details: str) -> None:
        """Log a damaged-part BlueFolder comment."""
        identity = self._resolve_identity(interaction)
        if not self._can_write_parts_issue(identity):
            raise app_commands.CheckFailure("You do not have permission to use this command.")
        result = await self.bot.container.bluefolder_service.log_parts_issue(
            sr_id,
            issue_type="damaged_part",
            details=details,
            requested_by_user_id=interaction.user.id,
        )
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(name="part_ordered", description="Log that a part was ordered in BlueFolder for a service request.")
    @app_commands.describe(vendor="Vendor or supplier name.", eta="Optional ETA text.", details="Optional extra order detail.")
    async def part_ordered(
        self,
        interaction: discord.Interaction,
        sr_id: int,
        vendor: str,
        eta: str | None = None,
        details: str | None = None,
    ) -> None:
        """Log a part-ordered BlueFolder comment."""
        detail_text = details or "Order submitted."
        await self._send_parts_update(
            interaction,
            sr_id=sr_id,
            details=detail_text,
            update_type="part_ordered",
            metadata={"vendor": vendor, **({"eta": eta} if eta else {})},
        )

    @app_commands.command(name="part_eta", description="Log an ETA update in BlueFolder for a service request.")
    @app_commands.describe(eta="ETA text or date/time.", carrier="Optional carrier name.", details="Optional extra ETA detail.")
    async def part_eta(
        self,
        interaction: discord.Interaction,
        sr_id: int,
        eta: str,
        carrier: str | None = None,
        details: str | None = None,
    ) -> None:
        """Log a part-ETA BlueFolder comment."""
        detail_text = details or "ETA updated."
        metadata = {"eta": eta, **({"carrier": carrier} if carrier else {})}
        await self._send_parts_update(interaction, sr_id=sr_id, details=detail_text, update_type="part_eta", metadata=metadata)

    @app_commands.command(name="part_tracking", description="Log a tracking update in BlueFolder for a service request.")
    @app_commands.describe(
        tracking_number="Tracking number or reference.",
        carrier="Optional carrier name.",
        eta="Optional ETA text.",
        details="Optional extra tracking detail.",
    )
    async def part_tracking(
        self,
        interaction: discord.Interaction,
        sr_id: int,
        tracking_number: str,
        carrier: str | None = None,
        eta: str | None = None,
        details: str | None = None,
    ) -> None:
        """Log a part-tracking BlueFolder comment."""
        detail_text = details or "Tracking posted."
        metadata = {
            "tracking_number": tracking_number,
            **({"carrier": carrier} if carrier else {}),
            **({"eta": eta} if eta else {}),
        }
        await self._send_parts_update(
            interaction,
            sr_id=sr_id,
            details=detail_text,
            update_type="part_tracking",
            metadata=metadata,
        )

    @app_commands.command(name="part_received", description="Log that a part was received in BlueFolder for a service request.")
    @app_commands.describe(received_from="Optional vendor, carrier, or source.", details="Receipt detail.")
    async def part_received(
        self,
        interaction: discord.Interaction,
        sr_id: int,
        details: str,
        received_from: str | None = None,
    ) -> None:
        """Log a part-received BlueFolder comment."""
        metadata = {"received_from": received_from} if received_from else None
        await self._send_parts_update(
            interaction,
            sr_id=sr_id,
            details=details,
            update_type="part_received",
            metadata=metadata,
        )

    @app_commands.command(name="part_ready", description="Log that a service request is ready for scheduling after parts arrival.")
    @app_commands.describe(ready_note="Optional scheduling note.", details="Ready detail.")
    async def part_ready(
        self,
        interaction: discord.Interaction,
        sr_id: int,
        details: str,
        ready_note: str | None = None,
    ) -> None:
        """Log a part-ready BlueFolder comment."""
        metadata = {"ready_note": ready_note} if ready_note else None
        await self._send_parts_update(
            interaction,
            sr_id=sr_id,
            details=details,
            update_type="part_ready",
            metadata=metadata,
        )

    @app_commands.command(name="part_request", description="Create a new tracked parts request.")
    @app_commands.describe(
        reference="Service request id, job reference, or other parts reference.",
        description="Short description of the needed part or issue.",
    )
    async def part_request(self, interaction: discord.Interaction, reference: str, description: str) -> None:
        """Create a tracked parts request."""
        identity = self._resolve_identity(interaction)
        if not self._can_submit_parts_request(identity):
            raise app_commands.CheckFailure("You do not have permission to use this command.")
        result = await self.bot.container.parts_cannon_service.create_request(
            PartRequestCreate(
                reference=reference,
                description=description,
                requested_by_user_id=interaction.user.id,
                technician_bluefolder_user_id=identity.bluefolder_user_id,
                requester_is_admin=identity.is_admin,
            )
        )
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(name="my_part_requests", description="List your tracked parts requests.")
    @app_commands.describe(
        status="Optional status filter: requested, ordered, received, resolved, cancelled.",
        unsynced_only="Only show requests that still need to be handed off downstream.",
    )
    async def my_part_requests(
        self,
        interaction: discord.Interaction,
        status: str | None = None,
        unsynced_only: bool = False,
    ) -> None:
        """List the caller's own tracked parts requests."""
        identity = self._resolve_identity(interaction)
        if not self._can_submit_parts_request(identity):
            raise app_commands.CheckFailure("You do not have permission to use this command.")
        result = await self.bot.container.parts_cannon_service.list_requests(
            status=status,
            requested_by_user_id=interaction.user.id,
            only_unsynced=unsynced_only,
        )
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(name="part_requests", description="List tracked parts requests.")
    @app_commands.describe(
        status="Optional status filter: requested, ordered, received, resolved, cancelled.",
        unsynced_only="Only show requests that still need to be handed off downstream.",
    )
    async def part_requests(
        self,
        interaction: discord.Interaction,
        status: str | None = None,
        unsynced_only: bool = False,
    ) -> None:
        """List tracked parts requests, optionally filtered by status."""
        identity = self._resolve_identity(interaction)
        if not self._can_use_parts_queue(identity):
            raise app_commands.CheckFailure("You do not have permission to use this command.")
        result = await self.bot.container.parts_cannon_service.list_requests(
            status=status,
            only_unsynced=unsynced_only,
        )
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(name="part_request_detail", description="Show full detail for a tracked parts request.")
    async def part_request_detail(self, interaction: discord.Interaction, request_id: int) -> None:
        """Show a detailed tracked parts request view."""
        identity = self._resolve_identity(interaction)
        if not self._can_use_parts_queue(identity):
            raise app_commands.CheckFailure("You do not have permission to use this command.")
        result = await self.bot.container.parts_cannon_service.get_request(request_id)
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(name="part_update", description="Update the status of a tracked parts request.")
    @app_commands.describe(
        request_id="Tracked parts request id.",
        status="New status: requested, ordered, received, resolved, cancelled.",
    )
    async def part_update(self, interaction: discord.Interaction, request_id: int, status: str) -> None:
        """Update a tracked parts request status."""
        identity = self._resolve_identity(interaction)
        if not self._can_use_parts_queue(identity):
            raise app_commands.CheckFailure("You do not have permission to use this command.")
        result = await self.bot.container.parts_cannon_service.update_request(
            PartRequestUpdate(
                request_id=request_id,
                status=status,
                updated_by_user_id=interaction.user.id,
            )
        )
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(name="part_claim", description="Claim a tracked parts request for yourself.")
    async def part_claim(self, interaction: discord.Interaction, request_id: int) -> None:
        """Assign a tracked parts request to the current parts user."""
        identity = self._resolve_identity(interaction)
        if not self._can_use_parts_queue(identity):
            raise app_commands.CheckFailure("You do not have permission to use this command.")
        result = await self.bot.container.parts_cannon_service.claim_request(
            PartRequestClaim(
                request_id=request_id,
                parts_user_id=interaction.user.id,
                updated_by_user_id=interaction.user.id,
            )
        )
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(name="part_unclaim", description="Remove the current parts assignment from a tracked request.")
    async def part_unclaim(self, interaction: discord.Interaction, request_id: int) -> None:
        """Unassign a tracked parts request."""
        identity = self._resolve_identity(interaction)
        if not self._can_use_parts_queue(identity):
            raise app_commands.CheckFailure("You do not have permission to use this command.")
        result = await self.bot.container.parts_cannon_service.claim_request(
            PartRequestClaim(
                request_id=request_id,
                parts_user_id=None,
                updated_by_user_id=interaction.user.id,
            )
        )
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(name="part_sync", description="Export the tracked parts queue to the configured parts workflow path.")
    async def part_sync(self, interaction: discord.Interaction) -> None:
        """Sync the tracked parts queue into the downstream handoff file."""
        identity = self._resolve_identity(interaction)
        if not self._can_use_parts_queue(identity):
            raise app_commands.CheckFailure("You do not have permission to use this command.")
        result = await self.bot.container.parts_cannon_service.sync_requests_to_parts_system()
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(name="part_reconcile", description="Import downstream parts receipts into the tracked queue.")
    async def part_reconcile(self, interaction: discord.Interaction) -> None:
        """Reconcile downstream parts receipts back into Ops Hub."""
        identity = self._resolve_identity(interaction)
        if not self._can_use_parts_queue(identity):
            raise app_commands.CheckFailure("You do not have permission to use this command.")
        result = await self.bot.container.parts_cannon_service.reconcile_requests_from_parts_system()
        await interaction.response.send_message(result.message, ephemeral=True)

    def _resolve_identity(self, interaction: discord.Interaction):
        """Resolve the invoking Discord user into an Ops Hub technician/admin identity."""
        user_roles = getattr(interaction.user, "roles", None)
        role_ids = {getattr(role, "id", None) for role in user_roles or [] if getattr(role, "id", None) is not None}
        return self.bot.container.technician_directory_service.resolve_identity(
            user_id=interaction.user.id,
            role_ids=role_ids,
        )

    async def _send_parts_update(
        self,
        interaction: discord.Interaction,
        *,
        sr_id: int,
        details: str,
        update_type: str,
        metadata: dict[str, str] | None = None,
    ) -> None:
        """Log a standardized BlueFolder parts update after access checks."""
        identity = self._resolve_identity(interaction)
        if not self._can_write_parts_update(identity):
            raise app_commands.CheckFailure("You do not have permission to use this command.")
        result = await self.bot.container.bluefolder_service.log_parts_update(
            sr_id,
            update_type=update_type,
            details=details,
            requested_by_user_id=interaction.user.id,
            metadata=metadata,
        )
        await interaction.response.send_message(result.message, ephemeral=True)

    def _can_use_job_commands(self, identity) -> bool:
        """Return whether the user can access job and assignments commands."""
        return identity.is_admin or identity.is_technician or identity.is_dispatcher

    def _can_submit_parts_request(self, identity) -> bool:
        """Return whether the user can create and view their own parts requests."""
        return identity.is_admin or identity.is_parts or identity.is_technician

    def _can_use_parts_queue(self, identity) -> bool:
        """Return whether the user can access the managed parts queue."""
        return identity.is_admin or identity.is_parts

    def _can_view_parts_context(self, identity) -> bool:
        """Return whether the user can view BlueFolder-native parts context."""
        return identity.is_admin or identity.is_parts or identity.is_dispatcher or identity.is_technician

    def _can_write_parts_issue(self, identity) -> bool:
        """Return whether the user can log BlueFolder parts issue comments."""
        return identity.is_admin or identity.is_parts or identity.is_technician

    def _can_write_parts_update(self, identity) -> bool:
        """Return whether the user can log BlueFolder parts status updates."""
        return identity.is_admin or identity.is_parts

    def _can_upload_sr_photo(self, identity) -> bool:
        """Return whether the user can upload or archive service-request photos."""
        return identity.is_admin or identity.is_technician

    async def _attachment_payload(self, attachment: discord.Attachment) -> PhotoAttachmentPayload:
        """Read a Discord attachment into the service-layer payload shape."""
        return PhotoAttachmentPayload(
            filename=attachment.filename,
            content_type=attachment.content_type,
            data=await attachment.read(),
        )


async def setup(bot: OpsHubBot) -> None:
    """Load the operations cog."""
    await bot.add_cog(OperationsCog(bot))
