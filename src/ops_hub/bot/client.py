"""Discord bot client wiring."""

from __future__ import annotations

import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

from ops_hub.bot.extensions import EXTENSIONS
from ops_hub.core.config import Settings
from ops_hub.core.container import ServiceContainer
from ops_hub.models.requests import PhotoIngestMessage


logger = logging.getLogger(__name__)


class LoggingCommandTree(app_commands.CommandTree["OpsHubBot"]):
    """Command tree that records app-command start timing for logging."""

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if isinstance(self.client, OpsHubBot):
            self.client._record_app_command_start(interaction)
        return await super().interaction_check(interaction)


class OpsHubBot(commands.Bot):
    """Discord bot for unified operations workflows."""

    def __init__(self, *, settings: Settings, container: ServiceContainer) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.messages = True
        intents.message_content = settings.enable_message_content_intent
        super().__init__(command_prefix="!", intents=intents, tree_cls=LoggingCommandTree)
        self.settings = settings
        self.container = container
        self._interaction_started_at: dict[int, float] = {}

    async def setup_hook(self) -> None:
        """Load extensions and sync commands."""
        for extension in EXTENSIONS:
            await self.load_extension(extension)

        try:
            if self.settings.guild_id is not None:
                guild = discord.Object(id=self.settings.guild_id)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                logger.info("Synced commands to guild", extra={"guild_id": self.settings.guild_id})
            else:
                await self.tree.sync()
                logger.info("Synced global commands")
        except Exception:
            logger.exception(
                "Failed to sync application commands",
                extra={"guild_id": self.settings.guild_id},
            )
            raise

    async def on_ready(self) -> None:
        """Log bot identity when ready."""
        if self.user is None:
            return
        self.container.notification_service.configure_sender(self._send_notice_to_channel)
        logger.info(
            "Ops Hub bot ready",
            extra={
                "bot_user": str(self.user),
                "bot_id": self.user.id,
                "message_content_intent": self.settings.enable_message_content_intent,
            },
        )

    async def on_app_command_completion(
        self,
        interaction: discord.Interaction,
        command: app_commands.Command[object, ..., object] | app_commands.ContextMenu,
    ) -> None:
        """Log successful application-command completion."""
        context = self._interaction_context(interaction)
        context["command"] = getattr(command, "qualified_name", None) or getattr(command, "name", None)
        context["duration_ms"] = self._pop_interaction_duration(interaction)
        logger.info("Application command completed", extra=context)

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
        context = self._interaction_context(interaction)
        context["duration_ms"] = self._pop_interaction_duration(interaction)
        logger.exception("Application command failed", exc_info=error, extra=context)

        message = "Ops Hub hit an unexpected error."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except Exception:
            logger.exception(
                "Failed to send application command error response",
                extra=self._interaction_context(interaction),
            )

    def _interaction_context(self, interaction: discord.Interaction) -> dict[str, int | str | None]:
        """Build a consistent log context for Discord interaction handlers."""
        return {
            "command": getattr(getattr(interaction, "command", None), "name", None),
            "interaction_id": getattr(interaction, "id", None),
            "user_id": getattr(getattr(interaction, "user", None), "id", None),
            "guild_id": getattr(interaction, "guild_id", None),
            "channel_id": getattr(interaction, "channel_id", None),
        }

    def _record_app_command_start(self, interaction: discord.Interaction) -> None:
        """Track application-command start and emit the initial receipt log."""
        if interaction.type != discord.InteractionType.application_command:
            return
        interaction_id = getattr(interaction, "id", None)
        if interaction_id is not None:
            self._interaction_started_at[interaction_id] = time.monotonic()
        logger.info("Application command received", extra=self._interaction_context(interaction))

    def _pop_interaction_duration(self, interaction: discord.Interaction) -> int | None:
        """Return elapsed command time in milliseconds when a start was recorded."""
        interaction_id = getattr(interaction, "id", None)
        if interaction_id is None:
            return None
        started_at = self._interaction_started_at.pop(interaction_id, None)
        if started_at is None:
            return None
        return int((time.monotonic() - started_at) * 1000)

    async def _send_notice_to_channel(self, channel_id: int, topic: str, message: str) -> None:
        """Route Ops Hub notices into a configured Discord channel."""
        channel = self.get_channel(channel_id)
        if channel is None:
            fetched_channel = await self.fetch_channel(channel_id)
            channel = fetched_channel
        if not isinstance(channel, discord.abc.Messageable):
            raise RuntimeError(f"Configured notification channel `{channel_id}` is not messageable.")
        await channel.send(f"[{topic}] {message}")


def build_bot(*, settings: Settings, container: ServiceContainer) -> OpsHubBot:
    """Construct the Discord bot instance."""
    return OpsHubBot(settings=settings, container=container)
