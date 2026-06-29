"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR.parent / ".env")


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    """Runtime configuration for Flask, Gmail, SMTP, and scheduler services."""

    base_dir: Path = BASE_DIR
    database_dir: Path = BASE_DIR / "database"
    logs_dir: Path = BASE_DIR / "logs"
    backups_dir: Path = BASE_DIR / "backups"
    email_templates_dir: Path = BASE_DIR / "templates" / "email"

    secret_key: str = os.getenv("SECRET_KEY", "change-me-in-production")
    dashboard_username: str = os.getenv("DASHBOARD_USERNAME", "admin")
    dashboard_password: str = os.getenv("DASHBOARD_PASSWORD", "leadflow")
    session_timeout_minutes: int = int(os.getenv("SESSION_TIMEOUT_MINUTES", "60"))

    gmail_label_name: str = os.getenv("GMAIL_LABEL_NAME", "Follow Up")
    gmail_credentials_file: str = os.getenv("GMAIL_CREDENTIALS_FILE", "credentials.json")
    gmail_token_file: str = os.getenv("GMAIL_TOKEN_FILE", "token.json")
    auto_remove_gmail_label: bool = _bool("AUTO_REMOVE_GMAIL_LABEL", False)

    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_username: str = os.getenv("SMTP_USERNAME", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from_email: str = os.getenv("SMTP_FROM_EMAIL", os.getenv("SMTP_USERNAME", ""))
    smtp_from_name: str = os.getenv("SMTP_FROM_NAME", "LeadFlow AI")
    smtp_tls: bool = _bool("SMTP_TLS", True)
    smtp_ssl: bool = _bool("SMTP_SSL", False)
    max_retry_count: int = int(os.getenv("MAX_RETRY_COUNT", "3"))
    retry_delay_minutes: int = int(os.getenv("RETRY_DELAY_MINUTES", "20"))

    business_start_hour: int = int(os.getenv("BUSINESS_START_HOUR", "9"))
    business_end_hour: int = int(os.getenv("BUSINESS_END_HOUR", "17"))
    business_timezone: str = os.getenv("BUSINESS_TIMEZONE", "UTC")
    weekdays_only: bool = _bool("WEEKDAYS_ONLY", True)

    scheduler_interval_minutes: int = int(os.getenv("SCHEDULER_INTERVAL_MINUTES", "5"))
    notification_enabled: bool = _bool("NOTIFICATION_ENABLED", True)
    sound_enabled: bool = _bool("SOUND_ENABLED", True)
    log_retention_days: int = int(os.getenv("LOG_RETENTION_DAYS", "30"))
    rate_limit_per_minute: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "120"))

    @property
    def database_url(self) -> str:
        """Return SQLAlchemy database URL."""
        return os.getenv(
            "DATABASE_URL",
            f"sqlite:///{self.database_dir / 'leadflow_ai.sqlite3'}",
        )


config = Config()
for directory in (config.database_dir, config.logs_dir, config.backups_dir, config.email_templates_dir):
    directory.mkdir(parents=True, exist_ok=True)

