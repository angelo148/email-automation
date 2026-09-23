from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    app_name: str = "MailFlow"
    app_version: str = "0.2.0"

    environment: Literal[
        "development",
        "test",
        "production",
    ] = "development"

    debug: bool = False

    log_level: Literal[
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    ] = "DEBUG"

    companies_file: Path = Path("data/3rd Party- Ticket Support.xlsx")

    send_job_db_file: Path = Path("app_data/send_jobs.sqlite3")

    scheduler_enabled: bool = True
    scheduler_poll_seconds: int = Field(default=10, ge=1, le=300)
    schedule_late_grace_seconds: int = Field(default=300, ge=0, le=86400)

    microsoft_client_id: str | None = None
    microsoft_client_secret: str | None = None

    # Kept for backward compatibility with the existing project.
    microsoft_tenant_id: str | None = None

    # Existing SPA redirect. It can remain registered in Entra.
    microsoft_redirect_uri: str = "http://localhost:8000"

    # Server-side authorization-code callback used by the persistent login.
    microsoft_callback_uri: str = "http://localhost:8000/auth/callback"

    microsoft_fixed_sender_email: str = ""

    # Encrypted with Windows DPAPI by msal-extensions.
    microsoft_token_cache_file: Path = Path("auth_data/microsoft_token_cache.bin")

    allowed_hosts: list[str] = Field(
        default_factory=lambda: [
            "localhost",
            "127.0.0.1",
            "testserver",
        ]
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_settings(self) -> "Settings":
        if self.environment == "production" and self.debug:
            raise ValueError("DEBUG must be false when ENVIRONMENT=production")

        if self.environment == "production":
            if not self.microsoft_client_id:
                raise ValueError("MICROSOFT_CLIENT_ID is required in production.")

            if not self.microsoft_client_secret:
                raise ValueError("MICROSOFT_CLIENT_SECRET is required in production.")

            if not self.microsoft_fixed_sender_email:
                raise ValueError(
                    "MICROSOFT_FIXED_SENDER_EMAIL is required in production."
                )

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
