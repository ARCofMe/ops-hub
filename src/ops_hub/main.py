"""Application entrypoint for Ops Hub."""

from __future__ import annotations

import logging

from ops_hub.bot.client import build_bot
from ops_hub.core.config import load_settings
from ops_hub.core.container import build_container
from ops_hub.core.logging import configure_logging


logger = logging.getLogger(__name__)


def main() -> int:
    """Start the Discord bot."""
    settings = load_settings()
    settings.validate_or_raise()
    configure_logging(settings.log_level)

    logger.info("Starting Ops Hub", extra={"environment": settings.environment})
    container = build_container(settings)
    bot = build_bot(settings=settings, container=container)
    bot.run(settings.discord_token)
    return 0

