"""Application entrypoint for Ops Hub."""

from __future__ import annotations

import logging

import urllib3

from ops_hub.api_server import build_api_server
from ops_hub.bot.client import build_bot
from ops_hub.core.config import load_settings
from ops_hub.core.container import build_container
from ops_hub.core.logging import configure_logging
from ops_hub.policy_runner import build_policy_runner


logger = logging.getLogger(__name__)


def _suppress_insecure_request_warnings(*, verify_ssl: bool | None) -> None:
    """Hide urllib3 TLS warnings for the current IP-based BlueFolder setup."""
    if verify_ssl is not False:
        return
    try:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        return


def main() -> int:
    """Start the Discord bot."""
    settings = load_settings()
    configure_logging(settings.log_level)
    settings.validate_or_raise()
    _suppress_insecure_request_warnings(verify_ssl=settings.bluefolder_verify_ssl)

    logger.info("Starting Ops Hub", extra={"environment": settings.environment})
    container = build_container(settings)
    api_server = build_api_server(settings=settings, container=container)
    policy_runner = build_policy_runner(settings=settings, container=container)
    api_server.start()
    policy_runner.start()
    bot = build_bot(settings=settings, container=container)
    try:
        bot.run(settings.discord_token)
    except Exception:
        logger.exception("Ops Hub failed during startup or runtime")
        raise
    finally:
        policy_runner.stop()
        api_server.stop()
    return 0
