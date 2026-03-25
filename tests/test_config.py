"""Configuration tests for Ops Hub."""

from ops_hub.core.config import Settings


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "discord_token": "token",
        "guild_id": None,
        "admin_user_ids": [],
        "admin_role_ids": [],
        "technician_user_ids": [],
        "technician_role_ids": [],
        "parts_user_ids": [],
        "parts_role_ids": [],
        "dispatcher_user_ids": [],
        "dispatcher_role_ids": [],
        "technician_bluefolder_user_map": {},
        "technician_mapping_file": None,
        "parts_request_file": None,
        "notification_channel_id": None,
        "notification_channel_map": {},
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


def test_legacy_operator_settings_merge_into_technician_settings() -> None:
    settings = _settings(
        operator_user_ids=[42],
        operator_role_ids=[7],
        operator_bluefolder_user_map={42: 13051},
        operator_mapping_file="legacy.json",
    )

    assert settings.technician_user_ids == [42]
    assert settings.technician_role_ids == [7]
    assert settings.technician_bluefolder_user_map == {42: 13051}
    assert settings.technician_mapping_file == "legacy.json"


def test_validation_errors_reject_non_positive_admin_user_ids() -> None:
    settings = _settings(admin_user_ids=[123, 0])

    errors = settings.validation_errors()

    assert "OPS_HUB_ADMIN_USER_IDS must contain only positive Discord user IDs." in errors


def test_validation_errors_reject_non_positive_admin_role_ids() -> None:
    settings = _settings(admin_role_ids=[-1])

    errors = settings.validation_errors()

    assert "OPS_HUB_ADMIN_ROLE_IDS must contain only positive Discord role IDs." in errors


def test_validation_errors_reject_non_positive_technician_user_ids() -> None:
    settings = _settings(technician_user_ids=[0])

    errors = settings.validation_errors()

    assert "OPS_HUB_TECHNICIAN_USER_IDS must contain only positive Discord user IDs." in errors


def test_validation_errors_reject_non_positive_technician_role_ids() -> None:
    settings = _settings(technician_role_ids=[-7])

    errors = settings.validation_errors()

    assert "OPS_HUB_TECHNICIAN_ROLE_IDS must contain only positive Discord role IDs." in errors


def test_validation_errors_reject_non_positive_parts_user_ids() -> None:
    settings = _settings(parts_user_ids=[0])

    errors = settings.validation_errors()

    assert "OPS_HUB_PARTS_USER_IDS must contain only positive Discord user IDs." in errors


def test_validation_errors_reject_non_positive_parts_role_ids() -> None:
    settings = _settings(parts_role_ids=[-7])

    errors = settings.validation_errors()

    assert "OPS_HUB_PARTS_ROLE_IDS must contain only positive Discord role IDs." in errors


def test_validation_errors_reject_non_positive_dispatcher_user_ids() -> None:
    settings = _settings(dispatcher_user_ids=[0])

    errors = settings.validation_errors()

    assert "OPS_HUB_DISPATCHER_USER_IDS must contain only positive Discord user IDs." in errors


def test_validation_errors_reject_non_positive_dispatcher_role_ids() -> None:
    settings = _settings(dispatcher_role_ids=[-7])

    errors = settings.validation_errors()

    assert "OPS_HUB_DISPATCHER_ROLE_IDS must contain only positive Discord role IDs." in errors


def test_validation_errors_reject_non_positive_technician_map_keys() -> None:
    settings = _settings(technician_bluefolder_user_map={0: 13051})

    errors = settings.validation_errors()

    assert "OPS_HUB_TECHNICIAN_BLUEFOLDER_USER_MAP keys must contain only positive Discord user IDs." in errors


def test_validation_errors_reject_non_positive_technician_map_values() -> None:
    settings = _settings(technician_bluefolder_user_map={42: 0})

    errors = settings.validation_errors()

    assert "OPS_HUB_TECHNICIAN_BLUEFOLDER_USER_MAP values must contain only positive BlueFolder user IDs." in errors


def test_validation_errors_reject_non_positive_notification_channel_id() -> None:
    settings = _settings(notification_channel_id=0)

    errors = settings.validation_errors()

    assert "OPS_HUB_NOTIFICATION_CHANNEL_ID must be a positive Discord channel ID." in errors


def test_validation_errors_reject_non_positive_notification_channel_map_values() -> None:
    settings = _settings(notification_channel_map={"parts": 0})

    errors = settings.validation_errors()

    assert "OPS_HUB_NOTIFICATION_CHANNEL_MAP values must contain only positive Discord channel IDs." in errors


def test_blank_optional_settings_values_are_treated_as_unset() -> None:
    settings = Settings(
        discord_token="token",
        guild_id="",
        photo_ingest_channel_id="",
        notification_channel_id="",
        bluefolder_timeout_seconds="",
        notification_channel_map="",
        technician_user_ids="",
        technician_bluefolder_user_map="",
    )

    assert settings.guild_id is None
    assert settings.photo_ingest_channel_id is None
    assert settings.notification_channel_id is None
    assert settings.bluefolder_timeout_seconds is None
    assert settings.notification_channel_map == {}
    assert settings.technician_user_ids == []
    assert settings.technician_bluefolder_user_map == {}


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


def test_validation_errors_require_complete_photo_mailbox_config() -> None:
    settings = _settings(photo_mailbox_imap_host="mail.example.com")

    errors = settings.validation_errors()

    assert "OPS_HUB_PHOTO_MAILBOX_IMAP_PORT must be a positive integer when mailbox scan is configured." in errors
    assert "OPS_HUB_PHOTO_MAILBOX_IMAP_USERNAME is required when mailbox scan is configured." in errors
    assert "OPS_HUB_PHOTO_MAILBOX_IMAP_PASSWORD is required when mailbox scan is configured." in errors


def test_validation_errors_reject_non_positive_photo_mailbox_search_days() -> None:
    settings = _settings(photo_mailbox_search_days=0)

    errors = settings.validation_errors()

    assert "OPS_HUB_PHOTO_MAILBOX_SEARCH_DAYS must be greater than 0." in errors


def test_validation_errors_reject_non_positive_photo_compress_max_mb() -> None:
    settings = _settings(photo_compress_max_mb=0)

    errors = settings.validation_errors()

    assert "OPS_HUB_PHOTO_COMPRESS_MAX_MB must be greater than 0." in errors


def test_validation_errors_allow_bluefolder_account_and_base_url_together() -> None:
    settings = _settings(
        bluefolder_api_key="key",
        bluefolder_account_name="acme",
        bluefolder_base_url="https://acme.bluefolder.com/api/2.0",
    )

    errors = settings.validation_errors()

    assert errors == []
