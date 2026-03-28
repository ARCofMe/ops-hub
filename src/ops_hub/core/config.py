"""Environment-backed configuration for Ops Hub."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    discord_token: str = ""
    guild_id: int | None = None
    admin_user_ids: list[int] = []
    admin_role_ids: list[int] = []
    technician_user_ids: list[int] = []
    technician_role_ids: list[int] = []
    parts_user_ids: list[int] = []
    parts_role_ids: list[int] = []
    dispatcher_user_ids: list[int] = []
    dispatcher_role_ids: list[int] = []
    technician_bluefolder_user_map: dict[int, int] = {}
    technician_mapping_file: str | None = None
    member_export_path: str | None = None
    member_export_timestamped: bool = True
    parts_request_file: str | None = None
    notification_channel_id: int | None = None
    notification_channel_map: dict[str, int] = {}
    enable_message_content_intent: bool = True
    log_level: str = "INFO"
    environment: str = "dev"
    enable_technician_api: bool = False
    technician_api_host: str = "127.0.0.1"
    technician_api_port: int = 8787
    technician_api_token: str | None = None
    photo_ingest_channel_id: int | None = None
    photo_compress_max_dimension: int = 1800
    photo_compress_jpeg_quality: int = 82
    photo_feature_flags_file: str | None = None
    enable_mdlsn_upload: bool = True
    enable_photo_archive_handoff: bool = True
    enable_photo_mailbox_scan: bool = False
    enable_weekly_missing_photo_notices: bool = False
    photo_compress_max_mb: int = 5

    bluefolder_api_path: str | None = None
    bluefolder_api_key: str | None = None
    bluefolder_account_name: str | None = None
    bluefolder_base_url: str | None = None
    bluefolder_host_header: str | None = None
    bluefolder_verify_ssl: bool | None = None
    bluefolder_timeout_seconds: float | None = None
    bluebot_discord_extension_path: str | None = None
    photo_ingest_project_path: str | None = None
    photo_archive_smtp_host: str | None = None
    photo_archive_smtp_port: int | None = None
    photo_archive_smtp_username: str | None = None
    photo_archive_smtp_password: str | None = None
    photo_archive_smtp_use_tls: bool = True
    photo_archive_from_email: str | None = None
    photo_archive_to_email: str | None = None
    photo_mailbox_imap_host: str | None = None
    photo_mailbox_imap_port: int | None = None
    photo_mailbox_imap_username: str | None = None
    photo_mailbox_imap_password: str | None = None
    photo_mailbox_imap_use_ssl: bool = True
    photo_mailbox_folder: str = "INBOX"
    photo_mailbox_search_days: int = 21
    photo_required_sr_statuses: list[str] = []
    photo_required_tags: list[str] = ["model", "serial"]
    parts_cannon_project_path: str | None = None
    dispatch_project_path: str | None = None

    # Deprecated compatibility fields. Prefer the technician_* names.
    operator_user_ids: list[int] = []
    operator_role_ids: list[int] = []
    operator_bluefolder_user_map: dict[int, int] = {}
    operator_mapping_file: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="OPS_HUB_",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_blank_values(cls, data: Any) -> Any:
        """Treat blank optional env values as unset instead of failing to parse."""
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        list_fields = {
            "admin_user_ids",
            "admin_role_ids",
            "technician_user_ids",
            "technician_role_ids",
            "parts_user_ids",
            "parts_role_ids",
            "dispatcher_user_ids",
            "dispatcher_role_ids",
            "photo_required_sr_statuses",
            "photo_required_tags",
            "operator_user_ids",
            "operator_role_ids",
        }
        map_fields = {
            "technician_bluefolder_user_map",
            "notification_channel_map",
            "operator_bluefolder_user_map",
        }
        optional_scalar_fields = {
            "guild_id",
            "enable_technician_api",
            "technician_api_host",
            "technician_api_port",
            "technician_api_token",
            "technician_mapping_file",
            "member_export_path",
            "member_export_timestamped",
            "operator_mapping_file",
            "parts_request_file",
            "notification_channel_id",
            "photo_ingest_channel_id",
            "photo_compress_max_dimension",
            "photo_compress_jpeg_quality",
            "photo_feature_flags_file",
            "photo_compress_max_mb",
            "bluefolder_api_path",
            "bluefolder_api_key",
            "bluefolder_account_name",
            "bluefolder_base_url",
            "bluefolder_host_header",
            "bluefolder_verify_ssl",
            "bluefolder_timeout_seconds",
            "bluebot_discord_extension_path",
            "photo_ingest_project_path",
            "photo_archive_smtp_host",
            "photo_archive_smtp_port",
            "photo_archive_smtp_username",
            "photo_archive_smtp_password",
            "photo_archive_smtp_use_tls",
            "photo_archive_from_email",
            "photo_archive_to_email",
            "photo_mailbox_imap_host",
            "photo_mailbox_imap_port",
            "photo_mailbox_imap_username",
            "photo_mailbox_imap_password",
            "photo_mailbox_imap_use_ssl",
            "photo_mailbox_folder",
            "photo_mailbox_search_days",
            "parts_cannon_project_path",
            "dispatch_project_path",
        }

        for field in list_fields:
            if normalized.get(field) == "":
                normalized[field] = []
        for field in map_fields:
            if normalized.get(field) == "":
                normalized[field] = {}
        for field in optional_scalar_fields:
            if normalized.get(field) == "":
                normalized[field] = None
        return normalized

    @model_validator(mode="after")
    def apply_operator_compatibility(self) -> Settings:
        """Merge legacy operator settings into technician settings for compatibility."""
        self.technician_user_ids = sorted(set(self.technician_user_ids) | set(self.operator_user_ids))
        self.technician_role_ids = sorted(set(self.technician_role_ids) | set(self.operator_role_ids))

        merged_map = dict(self.operator_bluefolder_user_map)
        merged_map.update(self.technician_bluefolder_user_map)
        self.technician_bluefolder_user_map = merged_map

        if self.technician_mapping_file is None and self.operator_mapping_file is not None:
            self.technician_mapping_file = self.operator_mapping_file

        return self

    def validation_errors(self) -> list[str]:
        """Return configuration errors without raising."""
        errors: list[str] = []

        if not self.discord_token.strip():
            errors.append("OPS_HUB_DISCORD_TOKEN is required.")

        if not self.environment.strip():
            errors.append("OPS_HUB_ENVIRONMENT cannot be empty.")

        if self.enable_technician_api:
            if not self.technician_api_host.strip():
                errors.append("OPS_HUB_TECHNICIAN_API_HOST cannot be empty when technician API is enabled.")
            if self.technician_api_port <= 0:
                errors.append("OPS_HUB_TECHNICIAN_API_PORT must be greater than 0 when technician API is enabled.")
            if not (self.technician_api_token or "").strip():
                errors.append("OPS_HUB_TECHNICIAN_API_TOKEN is required when technician API is enabled.")

        if not self.log_level.strip():
            errors.append("OPS_HUB_LOG_LEVEL cannot be empty.")

        if any(user_id <= 0 for user_id in self.admin_user_ids):
            errors.append("OPS_HUB_ADMIN_USER_IDS must contain only positive Discord user IDs.")

        if any(role_id <= 0 for role_id in self.admin_role_ids):
            errors.append("OPS_HUB_ADMIN_ROLE_IDS must contain only positive Discord role IDs.")

        if any(user_id <= 0 for user_id in self.technician_user_ids):
            errors.append("OPS_HUB_TECHNICIAN_USER_IDS must contain only positive Discord user IDs.")

        if any(role_id <= 0 for role_id in self.technician_role_ids):
            errors.append("OPS_HUB_TECHNICIAN_ROLE_IDS must contain only positive Discord role IDs.")

        if any(user_id <= 0 for user_id in self.parts_user_ids):
            errors.append("OPS_HUB_PARTS_USER_IDS must contain only positive Discord user IDs.")

        if any(role_id <= 0 for role_id in self.parts_role_ids):
            errors.append("OPS_HUB_PARTS_ROLE_IDS must contain only positive Discord role IDs.")

        if any(user_id <= 0 for user_id in self.dispatcher_user_ids):
            errors.append("OPS_HUB_DISPATCHER_USER_IDS must contain only positive Discord user IDs.")

        if any(role_id <= 0 for role_id in self.dispatcher_role_ids):
            errors.append("OPS_HUB_DISPATCHER_ROLE_IDS must contain only positive Discord role IDs.")

        if any(user_id <= 0 for user_id in self.technician_bluefolder_user_map):
            errors.append(
                "OPS_HUB_TECHNICIAN_BLUEFOLDER_USER_MAP keys must contain only positive Discord user IDs."
            )

        if any(bluefolder_user_id <= 0 for bluefolder_user_id in self.technician_bluefolder_user_map.values()):
            errors.append(
                "OPS_HUB_TECHNICIAN_BLUEFOLDER_USER_MAP values must contain only positive BlueFolder user IDs."
            )

        if self.notification_channel_id is not None and self.notification_channel_id <= 0:
            errors.append("OPS_HUB_NOTIFICATION_CHANNEL_ID must be a positive Discord channel ID.")

        if any(channel_id <= 0 for channel_id in self.notification_channel_map.values()):
            errors.append("OPS_HUB_NOTIFICATION_CHANNEL_MAP values must contain only positive Discord channel IDs.")

        bluefolder_key = (self.bluefolder_api_key or "").strip()
        bluefolder_account = (self.bluefolder_account_name or "").strip()
        bluefolder_base_url = (self.bluefolder_base_url or "").strip()

        if bluefolder_key and not (bluefolder_account or bluefolder_base_url):
            errors.append(
                "OPS_HUB_BLUEFOLDER_API_KEY requires OPS_HUB_BLUEFOLDER_ACCOUNT_NAME or OPS_HUB_BLUEFOLDER_BASE_URL."
            )

        if (bluefolder_account or bluefolder_base_url) and not bluefolder_key:
            errors.append(
                "OPS_HUB_BLUEFOLDER_ACCOUNT_NAME or OPS_HUB_BLUEFOLDER_BASE_URL requires OPS_HUB_BLUEFOLDER_API_KEY."
            )

        if self.bluefolder_timeout_seconds is not None and float(self.bluefolder_timeout_seconds) <= 0:
            errors.append("OPS_HUB_BLUEFOLDER_TIMEOUT_SECONDS must be greater than 0 when set.")

        if self.photo_compress_max_dimension <= 0:
            errors.append("OPS_HUB_PHOTO_COMPRESS_MAX_DIMENSION must be greater than 0.")

        if self.photo_compress_jpeg_quality <= 0 or self.photo_compress_jpeg_quality > 95:
            errors.append("OPS_HUB_PHOTO_COMPRESS_JPEG_QUALITY must be between 1 and 95.")
        if self.photo_compress_max_mb <= 0:
            errors.append("OPS_HUB_PHOTO_COMPRESS_MAX_MB must be greater than 0.")

        archive_fields = [
            self.photo_archive_smtp_host,
            self.photo_archive_smtp_username,
            self.photo_archive_smtp_password,
            self.photo_archive_from_email,
            self.photo_archive_to_email,
        ]
        if any(value is not None and str(value).strip() for value in archive_fields):
            if not (self.photo_archive_smtp_host or "").strip():
                errors.append("OPS_HUB_PHOTO_ARCHIVE_SMTP_HOST is required when archive email is configured.")
            if self.photo_archive_smtp_port is None or self.photo_archive_smtp_port <= 0:
                errors.append("OPS_HUB_PHOTO_ARCHIVE_SMTP_PORT must be a positive integer when archive email is configured.")
            if not (self.photo_archive_from_email or "").strip():
                errors.append("OPS_HUB_PHOTO_ARCHIVE_FROM_EMAIL is required when archive email is configured.")
            if not (self.photo_archive_to_email or "").strip():
                errors.append("OPS_HUB_PHOTO_ARCHIVE_TO_EMAIL is required when archive email is configured.")

        mailbox_fields = [
            self.photo_mailbox_imap_host,
            self.photo_mailbox_imap_username,
            self.photo_mailbox_imap_password,
        ]
        if any(value is not None and str(value).strip() for value in mailbox_fields):
            if not (self.photo_mailbox_imap_host or "").strip():
                errors.append("OPS_HUB_PHOTO_MAILBOX_IMAP_HOST is required when mailbox scan is configured.")
            if self.photo_mailbox_imap_port is None or self.photo_mailbox_imap_port <= 0:
                errors.append("OPS_HUB_PHOTO_MAILBOX_IMAP_PORT must be a positive integer when mailbox scan is configured.")
            if not (self.photo_mailbox_imap_username or "").strip():
                errors.append("OPS_HUB_PHOTO_MAILBOX_IMAP_USERNAME is required when mailbox scan is configured.")
            if not (self.photo_mailbox_imap_password or "").strip():
                errors.append("OPS_HUB_PHOTO_MAILBOX_IMAP_PASSWORD is required when mailbox scan is configured.")

        if self.photo_mailbox_search_days <= 0:
            errors.append("OPS_HUB_PHOTO_MAILBOX_SEARCH_DAYS must be greater than 0.")

        for env_name, path_value in [
            ("OPS_HUB_BLUEFOLDER_API_PATH", self.bluefolder_api_path),
            ("OPS_HUB_BLUEBOT_DISCORD_EXTENSION_PATH", self.bluebot_discord_extension_path),
            ("OPS_HUB_PHOTO_INGEST_PROJECT_PATH", self.photo_ingest_project_path),
            ("OPS_HUB_PARTS_CANNON_PROJECT_PATH", self.parts_cannon_project_path),
            ("OPS_HUB_DISPATCH_PROJECT_PATH", self.dispatch_project_path),
        ]:
            errors.extend(self._directory_path_errors(env_name, path_value))

        for env_name, path_value in [
            ("OPS_HUB_TECHNICIAN_MAPPING_FILE", self.technician_mapping_file),
            ("OPS_HUB_MEMBER_EXPORT_PATH", self.member_export_path),
            ("OPS_HUB_PARTS_REQUEST_FILE", self.parts_request_file),
            ("OPS_HUB_PHOTO_FEATURE_FLAGS_FILE", self.photo_feature_flags_file),
        ]:
            errors.extend(self._file_target_path_errors(env_name, path_value))

        return errors

    def _directory_path_errors(self, env_name: str, path_value: str | None) -> list[str]:
        """Validate configured project/library directories."""
        if not (path_value or "").strip():
            return []

        path = Path(path_value).expanduser()
        if not path.exists():
            return [f"{env_name} does not exist: {path}"]
        if not path.is_dir():
            return [f"{env_name} must point to a directory: {path}"]
        return []

    def _file_target_path_errors(self, env_name: str, path_value: str | None) -> list[str]:
        """Validate configured file targets and their parent directories."""
        if not (path_value or "").strip():
            return []

        path = Path(path_value).expanduser()
        errors: list[str] = []
        if path.exists() and path.is_dir():
            errors.append(f"{env_name} must point to a file path, not a directory: {path}")

        parent = path.parent
        if parent.exists() and not parent.is_dir():
            errors.append(f"{env_name} parent path is not a directory: {parent}")
        return errors

    def validate_or_raise(self) -> None:
        """Fail fast on clearly invalid startup config."""
        errors = self.validation_errors()
        if errors:
            raise RuntimeError("Invalid Ops Hub configuration:\n- " + "\n- ".join(errors))


def load_settings() -> Settings:
    """Load Ops Hub settings from environment variables."""
    return Settings()
