"""Rotating application logging with dashboard persistence."""

from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler

from .config import config
from .database import session_scope
from .models import LogEntry


def configure_logging() -> logging.Logger:
    """Configure and return the app logger."""
    logger = logging.getLogger("leadflow_ai")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    file_handler = TimedRotatingFileHandler(
        config.logs_dir / "leadflow_ai.log",
        when="midnight",
        backupCount=config.log_retention_days,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


logger = configure_logging()


def log_event(level: str, category: str, message: str) -> None:
    """Write an event to logs and the dashboard log table."""
    getattr(logger, level.lower(), logger.info)("[%s] %s", category, message)
    try:
        with session_scope() as session:
            session.add(LogEntry(level=level.upper(), category=category, message=message))
    except Exception as exc:  # pragma: no cover - logging must never break callers
        logger.exception("Failed to persist log event: %s", exc)

