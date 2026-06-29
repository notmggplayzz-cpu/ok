"""SQLite backup management."""

from __future__ import annotations

import shutil
from datetime import datetime

from .config import config
from .logging_manager import log_event


class BackupManager:
    """Create and prune database backups."""

    def backup_database(self) -> str | None:
        """Create a timestamped SQLite backup and retain the newest 30."""
        db_path = config.database_dir / "leadflow_ai.sqlite3"
        if not db_path.exists():
            log_event("warning", "backup", "Database file does not exist yet")
            return None
        target = config.backups_dir / f"leadflow_ai_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.sqlite3"
        shutil.copy2(db_path, target)
        backups = sorted(config.backups_dir.glob("leadflow_ai_*.sqlite3"), reverse=True)
        for old_backup in backups[30:]:
            old_backup.unlink(missing_ok=True)
        log_event("info", "backup", f"Created database backup {target.name}")
        return str(target)


backup_manager = BackupManager()

