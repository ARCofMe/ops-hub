"""Environment-backed configuration for Ops Hub."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    discord_token: str = ""
    guild_id: int | None = None
    log_level: str = "INFO"
    environment: str = "dev"
    photo_ingest_channel_id: int | None = None

    bluefolder_api_path: str | None = None
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

        return errors

    def validate_or_raise(self) -> None:
        """Fail fast on clearly invalid startup config."""
        errors = self.validation_errors()
        if errors:
            raise RuntimeError("Invalid Ops Hub configuration:\n- " + "\n- ".join(errors))


def load_settings() -> Settings:
    """Load Ops Hub settings from environment variables."""
    return Settings()
