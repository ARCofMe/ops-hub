"""Discord bot client wiring."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from ops_hub.bot.extensions import EXTENSIONS
from ops_hub.core.config import Settings
from ops_hub.core.container import ServiceContainer
from ops_hub.models.requests import PhotoIngestMessage


logger = logging.getLogger(__name__)


class OpsHubBot(commands.Bot):
    """Discord bot for unified operations workflows."""

    def __init__(self, *, settings: Settings, container: ServiceContainer) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.messages = True
        super().__init__(command_prefix="!", intents=intents)
        self.settings = settings
        self.container = container

    async def setup_hook(self) -> None:
        """Load extensions and sync commands."""
        for extension in EXTENSIONS:
            await self.load_extension(extension)

        if self.settings.guild_id is not None:
            guild = discord.Object(id=self.settings.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info("Synced commands to guild", extra={"guild_id": self.settings.guild_id})
        else:
            await self.tree.sync()
            logger.info("Synced global commands")

    async def on_ready(self) -> None:
        """Log bot identity when ready."""
        if self.user is None:
            return
        logger.info("Ops Hub bot ready", extra={"bot_user": str(self.user), "bot_id": self.user.id})

    async def on_message(self, message: discord.Message) -> None:
        """Route message events into placeholder listeners without affecting existing projects."""
        if message.author.bot:
            return

        photo_result = await self.container.photo_ingest_service.handle_message(
            PhotoIngestMessage(
                channel_id=message.channel.id,
                message_id=message.id,
                author_id=message.author.id,
                content=message.content or "",
                attachment_count=len(message.attachments),
            )
        )
        if photo_result.handled:
            logger.info(
                "Photo ingest listener handled message",
                extra={
                    "channel_id": message.channel.id,
                    "message_id": message.id,
                    "status": photo_result.status,
                },
            )

        await self.process_commands(message)

    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: discord.app_commands.AppCommandError,
    ) -> None:
        """Return a minimal user-facing error and log the full context."""
        logger.exception(
            "Application command failed",
            exc_info=error,
            extra={
                "command": getattr(getattr(interaction, "command", None), "name", None),
                "user_id": getattr(getattr(interaction, "user", None), "id", None),
                "guild_id": getattr(interaction, "guild_id", None),
            },
        )

        message = "Ops Hub hit an unexpected error."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


def build_bot(*, settings: Settings, container: ServiceContainer) -> OpsHubBot:
    """Construct the Discord bot instance."""
    return OpsHubBot(settings=settings, container=container)
