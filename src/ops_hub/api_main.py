"""API-only entrypoint for local OpsHub ecosystem rehearsals."""

from __future__ import annotations

import logging
import time

from ops_hub.api_server import build_api_server
from ops_hub.core.config import Settings, load_settings
from ops_hub.core.container import build_container
from ops_hub.core.logging import configure_logging
from ops_hub.main import _suppress_insecure_request_warnings


logger = logging.getLogger(__name__)


def validate_api_settings(settings: Settings) -> None:
    """Validate only the settings required for the local API server."""
    errors = [
        error
        for error in settings.validation_errors()
        if error != "OPS_HUB_DISCORD_TOKEN is required."
    ]
    if errors:
        raise ValueError("Invalid Ops Hub API configuration:\n- " + "\n- ".join(errors))


def main() -> int:
    """Start only the technician/web API server without the Discord bot."""
    settings = load_settings()
    configure_logging(settings.log_level)
    validate_api_settings(settings)
    _suppress_insecure_request_warnings(verify_ssl=settings.bluefolder_verify_ssl)

    container = build_container(settings)
    api_server = build_api_server(settings=settings, container=container)
    api_server.start()
    logger.info(
        "Ops Hub API server running",
        extra={"host": settings.technician_api_host, "port": settings.technician_api_port},
    )
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping Ops Hub API server")
    finally:
        api_server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
