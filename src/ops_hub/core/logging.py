"""Logging setup for Ops Hub."""

from __future__ import annotations

import logging
from typing import Any


class OpsHubContextFilter(logging.Filter):
    """Populate stable log context keys so structured formatting stays readable."""

    DEFAULTS: dict[str, Any] = {
        "command": "-",
        "interaction_id": "-",
        "user_id": "-",
        "guild_id": "-",
        "channel_id": "-",
        "sr_id": "-",
        "bluefolder_user_id": "-",
        "topic": "-",
        "delivery": "-",
        "status": "-",
        "duration_ms": "-",
    }

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in self.DEFAULTS.items():
            if not hasattr(record, key):
                setattr(record, key, value)
        return True


def configure_logging(level: str = "INFO") -> None:
    """Configure application logging once at startup."""
    handler = logging.StreamHandler()
    handler.addFilter(OpsHubContextFilter())
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s "
            "| cmd=%(command)s interaction=%(interaction_id)s user=%(user_id)s "
            "guild=%(guild_id)s channel=%(channel_id)s sr=%(sr_id)s "
            "bf_user=%(bluefolder_user_id)s topic=%(topic)s delivery=%(delivery)s "
            "status=%(status)s duration_ms=%(duration_ms)s"
        )
    )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    root_logger.addHandler(handler)
