"""APScheduler job registration and lifecycle management."""

from __future__ import annotations

from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .backup_manager import backup_manager
from .config import config
from .database import session_scope
from .health_monitor import health_monitor
from .logging_manager import log_event
from .models import LogEntry, Setting
from .reply_detector import followup_sender, lead_importer, reply_detector


class LeadFlowScheduler:
    """Owns recurring background jobs."""

    def __init__(self) -> None:
        self.scheduler = BackgroundScheduler(timezone="UTC")

    def start(self) -> None:
        """Start scheduler with all jobs."""
        if self.scheduler.running:
            return
        interval = self._interval_minutes()
        self.scheduler.add_job(lead_importer.import_from_gmail, IntervalTrigger(minutes=interval), id="import_gmail_leads", replace_existing=True)
        self.scheduler.add_job(reply_detector.detect_replies, IntervalTrigger(minutes=1), id="detect_replies", replace_existing=True)
        self.scheduler.add_job(followup_sender.send_due_emails, IntervalTrigger(minutes=1), id="send_due_emails", replace_existing=True)
        self.scheduler.add_job(followup_sender.retry_failed_emails, IntervalTrigger(minutes=15), id="retry_failed_emails", replace_existing=True)
        self.scheduler.add_job(self.cleanup_logs, CronTrigger(hour=2, minute=15), id="cleanup_logs", replace_existing=True)
        self.scheduler.add_job(backup_manager.backup_database, CronTrigger(hour=2, minute=30), id="database_backup", replace_existing=True)
        self.scheduler.add_job(self.health_check, IntervalTrigger(minutes=10), id="health_check", replace_existing=True)
        self.scheduler.start()
        log_event("info", "scheduler", "Scheduler started")

    def stop(self) -> None:
        """Stop scheduler."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            log_event("info", "scheduler", "Scheduler stopped")

    def status(self) -> dict[str, str]:
        """Return scheduler status and next run times."""
        return {
            job.id: (job.next_run_time.isoformat() if job.next_run_time else "paused")
            for job in self.scheduler.get_jobs()
        }

    def cleanup_logs(self) -> None:
        """Remove old structured logs."""
        cutoff = datetime.utcnow() - timedelta(days=config.log_retention_days)
        with session_scope() as session:
            deleted = session.query(LogEntry).filter(LogEntry.created_at < cutoff).delete()
        if deleted:
            log_event("info", "logs", f"Cleaned {deleted} old log rows")

    def health_check(self) -> None:
        """Run lightweight local health checks."""
        failed = [item for item in health_monitor.all_checks(include_external=False) if not item.ok]
        if failed:
            log_event("warning", "health", "; ".join(f"{item.name}: {item.detail}" for item in failed))

    def _interval_minutes(self) -> int:
        with session_scope() as session:
            setting = session.get(Setting, "scheduler_interval_minutes")
            return int(setting.value) if setting else config.scheduler_interval_minutes


leadflow_scheduler = LeadFlowScheduler()

