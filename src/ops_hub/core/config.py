"""Environment-backed configuration for Ops Hub."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    discord_token: str = ""
    guild_id: int | None = None
    admin_user_ids: list[int] = []
    admin_role_ids: list[int] = []
    operator_user_ids: list[int] = []
    operator_role_ids: list[int] = []
    dispatcher_user_ids: list[int] = []
    dispatcher_role_ids: list[int] = []
    operator_bluefolder_user_map: dict[int, int] = {}
    operator_mapping_file: str | None = None
    log_level: str = "INFO"
    environment: str = "dev"
    photo_ingest_channel_id: int | None = None

    bluefolder_api_path: str | None = None
    bluefolder_api_key: str | None = None
    bluefolder_account_name: str | None = None
    bluefolder_base_url: str | None = None
    bluebot_discord_extension_path: str | None = None
    photo_ingest_project_path: str | None = None
    parts_cannon_project_path: str | None = None
    dispatch_project_path: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="OPS_HUB_",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def validation_errors(self) -> list[str]:
        """Return configuration errors without raising."""
        errors: list[str] = []

        if not self.discord_token.strip():
            errors.append("OPS_HUB_DISCORD_TOKEN is required.")

        if not self.environment.strip():
            errors.append("OPS_HUB_ENVIRONMENT cannot be empty.")

        if not self.log_level.strip():
            errors.append("OPS_HUB_LOG_LEVEL cannot be empty.")

        if any(user_id <= 0 for user_id in self.admin_user_ids):
            errors.append("OPS_HUB_ADMIN_USER_IDS must contain only positive Discord user IDs.")

        if any(role_id <= 0 for role_id in self.admin_role_ids):
            errors.append("OPS_HUB_ADMIN_ROLE_IDS must contain only positive Discord role IDs.")

        if any(user_id <= 0 for user_id in self.operator_user_ids):
            errors.append("OPS_HUB_OPERATOR_USER_IDS must contain only positive Discord user IDs.")

        if any(role_id <= 0 for role_id in self.operator_role_ids):
            errors.append("OPS_HUB_OPERATOR_ROLE_IDS must contain only positive Discord role IDs.")

        if any(user_id <= 0 for user_id in self.dispatcher_user_ids):
            errors.append("OPS_HUB_DISPATCHER_USER_IDS must contain only positive Discord user IDs.")

        if any(role_id <= 0 for role_id in self.dispatcher_role_ids):
            errors.append("OPS_HUB_DISPATCHER_ROLE_IDS must contain only positive Discord role IDs.")

        if any(user_id <= 0 for user_id in self.operator_bluefolder_user_map):
            errors.append(
                "OPS_HUB_OPERATOR_BLUEFOLDER_USER_MAP keys must contain only positive Discord user IDs."
            )

        if any(bluefolder_user_id <= 0 for bluefolder_user_id in self.operator_bluefolder_user_map.values()):
            errors.append(
                "OPS_HUB_OPERATOR_BLUEFOLDER_USER_MAP values must contain only positive BlueFolder user IDs."
            )

        bluefolder_key = (self.bluefolder_api_key or "").strip()
        bluefolder_account = (self.bluefolder_account_name or "").strip()
        bluefolder_base_url = (self.bluefolder_base_url or "").strip()

        if bluefolder_account and bluefolder_base_url:
            errors.append(
                "Set either OPS_HUB_BLUEFOLDER_ACCOUNT_NAME or OPS_HUB_BLUEFOLDER_BASE_URL, not both."
            )

        if bluefolder_key and not (bluefolder_account or bluefolder_base_url):
            errors.append(
                "OPS_HUB_BLUEFOLDER_API_KEY requires OPS_HUB_BLUEFOLDER_ACCOUNT_NAME or OPS_HUB_BLUEFOLDER_BASE_URL."
            )

        if (bluefolder_account or bluefolder_base_url) and not bluefolder_key:
            errors.append(
                "OPS_HUB_BLUEFOLDER_ACCOUNT_NAME or OPS_HUB_BLUEFOLDER_BASE_URL requires OPS_HUB_BLUEFOLDER_API_KEY."
            )

        return errors

    def validate_or_raise(self) -> None:
        """Fail fast on clearly invalid startup config."""
        errors = self.validation_errors()
        if errors:
            raise RuntimeError("Invalid Ops Hub configuration:\n- " + "\n- ".join(errors))


def load_settings() -> Settings:
    """Load Ops Hub settings from environment variables."""
    return Settings()
