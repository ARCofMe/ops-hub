"""Environment-backed configuration for Ops Hub."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    discord_token: str = ""
    guild_id: int | None = None
    log_level: str = "INFO"
    environment: str = "dev"

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

    def validate_or_raise(self) -> None:
        """Fail fast on clearly invalid startup config."""
        errors: list[str] = []
        if not self.discord_token.strip():
            errors.append("OPS_HUB_DISCORD_TOKEN is required.")
        if errors:
            raise RuntimeError("Invalid Ops Hub configuration:\n- " + "\n- ".join(errors))


def load_settings() -> Settings:
    """Load Ops Hub settings from environment variables."""
    return Settings()

