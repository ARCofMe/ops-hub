"""Configuration tests for Ops Hub."""

from ops_hub.core.config import Settings


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "discord_token": "token",
        "guild_id": None,
        "log_level": "INFO",
        "environment": "dev",
        "photo_ingest_channel_id": None,
        "bluefolder_api_path": None,
        "bluefolder_api_key": None,
        "bluefolder_account_name": None,
        "bluefolder_base_url": None,
        "bluebot_discord_extension_path": None,
        "photo_ingest_project_path": None,
        "parts_cannon_project_path": None,
        "dispatch_project_path": None,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_validation_errors_require_discord_token() -> None:
    settings = _settings(discord_token="")

    errors = settings.validation_errors()

    assert "OPS_HUB_DISCORD_TOKEN is required." in errors


def test_validation_errors_reject_blank_environment() -> None:
    settings = _settings(environment="   ")

    errors = settings.validation_errors()

    assert "OPS_HUB_ENVIRONMENT cannot be empty." in errors


def test_validation_errors_reject_blank_log_level() -> None:
    settings = _settings(log_level="")

    errors = settings.validation_errors()

    assert "OPS_HUB_LOG_LEVEL cannot be empty." in errors


def test_validate_or_raise_passes_for_valid_settings() -> None:
    settings = _settings()

    settings.validate_or_raise()


def test_validation_errors_require_bluefolder_account_or_base_url_with_key() -> None:
    settings = _settings(bluefolder_api_key="key")

    errors = settings.validation_errors()

    assert (
        "OPS_HUB_BLUEFOLDER_API_KEY requires OPS_HUB_BLUEFOLDER_ACCOUNT_NAME or OPS_HUB_BLUEFOLDER_BASE_URL."
        in errors
    )


def test_validation_errors_require_bluefolder_key_with_account() -> None:
    settings = _settings(bluefolder_account_name="acme")

    errors = settings.validation_errors()

    assert (
        "OPS_HUB_BLUEFOLDER_ACCOUNT_NAME or OPS_HUB_BLUEFOLDER_BASE_URL requires OPS_HUB_BLUEFOLDER_API_KEY."
        in errors
    )


def test_validation_errors_reject_bluefolder_account_and_base_url_together() -> None:
    settings = _settings(
        bluefolder_api_key="key",
        bluefolder_account_name="acme",
        bluefolder_base_url="https://acme.bluefolder.com/api/2.0",
    )

    errors = settings.validation_errors()

    assert (
        "Set either OPS_HUB_BLUEFOLDER_ACCOUNT_NAME or OPS_HUB_BLUEFOLDER_BASE_URL, not both."
        in errors
    )
