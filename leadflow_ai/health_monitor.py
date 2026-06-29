"""Health monitoring for database, scheduler, SMTP, Gmail, disk, and logs."""

from __future__ import annotations

import shutil
from dataclasses import dataclass

from sqlalchemy import text

from .config import config
from .database import session_scope
from .gmail_client import gmail_client
from .smtp_client import smtp_client


@dataclass(frozen=True)
class HealthItem:
    """Single health check result."""

    name: str
    ok: bool
    detail: str


class HealthMonitor:
    """Run operational health checks."""

    def check_database(self) -> HealthItem:
        """Verify database connectivity."""
        try:
            with session_scope() as session:
                session.execute(text("SELECT 1"))
            return HealthItem("Database", True, "Connected")
        except Exception as exc:
            return HealthItem("Database", False, str(exc))

    def check_smtp(self) -> HealthItem:
        """Verify SMTP connectivity."""
        ok, detail = smtp_client.test_connection()
        return HealthItem("SMTP", ok, detail)

    def check_gmail(self) -> HealthItem:
        """Verify Gmail connectivity."""
        try:
            gmail_client.get_label_id(config.gmail_label_name)
            return HealthItem("Gmail", True, "Authenticated")
        except Exception as exc:
            return HealthItem("Gmail", False, str(exc))

    def check_disk(self) -> HealthItem:
        """Report disk usage for the app folder."""
        usage = shutil.disk_usage(config.base_dir)
        percent = round((usage.used / usage.total) * 100, 1)
        return HealthItem("Disk Usage", percent < 95, f"{percent}% used")

    def check_log_size(self) -> HealthItem:
        """Report total log size."""
        size = sum(path.stat().st_size for path in config.logs_dir.glob("*") if path.is_file())
        return HealthItem("Log Size", size < 250 * 1024 * 1024, f"{round(size / 1024 / 1024, 2)} MB")

    def all_checks(self, include_external: bool = False) -> list[HealthItem]:
        """Run health checks, optionally including network-dependent providers."""
        checks = [self.check_database(), self.check_disk(), self.check_log_size()]
        if include_external:
            checks.extend([self.check_smtp(), self.check_gmail()])
        return checks


health_monitor = HealthMonitor()

