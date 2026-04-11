"""API-only entrypoint tests."""

from __future__ import annotations

from ops_hub.api_main import validate_api_settings
from ops_hub.core.config import Settings


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "discord_token": "",
        "environment": "dev",
        "enable_technician_api": True,
        "technician_api_host": "127.0.0.1",
        "technician_api_port": 8787,
        "technician_api_token": "secret",
        "workflow_policy_interval_seconds": 60,
        "log_level": "INFO",
    }
    values.update(overrides)
    return Settings(**values)


def test_api_settings_allow_missing_discord_token() -> None:
    validate_api_settings(_settings())


def test_api_settings_still_require_technician_api_token() -> None:
    try:
        validate_api_settings(_settings(technician_api_token=""))
    except ValueError as exc:
        assert "OPS_HUB_TECHNICIAN_API_TOKEN is required when technician API is enabled." in str(exc)
    else:
        raise AssertionError("Expected API validation to require technician API token")
