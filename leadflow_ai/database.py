"""Database engine, sessions, and initialization helpers."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, scoped_session, sessionmaker

from .config import config


class Base(DeclarativeBase):
    """Declarative model base."""


engine = create_engine(
    config.database_url,
    connect_args={"check_same_thread": False} if config.database_url.startswith("sqlite") else {},
    pool_pre_ping=True,
    future=True,
)
SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True))


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    """Enable SQLite foreign keys and better durability."""
    if config.database_url.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional session scope."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create database tables and seed default application data."""
    from .models import FollowUpSequence, Setting, Template  # noqa: WPS433

    Base.metadata.create_all(bind=engine)
    with session_scope() as session:
        if session.query(Template).count() == 0:
            session.add_all(
                [
                    Template(
                        name="followup1",
                        subject="Quick follow-up: {{ subject }}",
                        html_body="<p>Hi {{ name }},</p><p>Just checking in on my previous note.</p><p>Best,<br>{{ service }}</p>",
                        text_body="Hi {{ name }},\n\nJust checking in on my previous note.\n\nBest,\n{{ service }}",
                    ),
                    Template(
                        name="followup2",
                        subject="Still worth a quick chat?",
                        html_body="<p>Hi {{ name }},</p><p>Wanted to bubble this back up in case timing is better now.</p>",
                        text_body="Hi {{ name }},\n\nWanted to bubble this back up in case timing is better now.",
                    ),
                ]
            )
        if session.query(FollowUpSequence).count() == 0:
            session.add_all(
                [
                    FollowUpSequence(step_number=1, delay_days=2, template_name="followup1", enabled=True),
                    FollowUpSequence(step_number=2, delay_days=4, template_name="followup2", enabled=True),
                ]
            )
        defaults = {
            "business_start_hour": str(config.business_start_hour),
            "business_end_hour": str(config.business_end_hour),
            "business_timezone": config.business_timezone,
            "weekdays_only": str(config.weekdays_only),
            "scheduler_interval_minutes": str(config.scheduler_interval_minutes),
            "notification_enabled": str(config.notification_enabled),
            "sound_enabled": str(config.sound_enabled),
            "theme": "dark",
            "max_retry_count": str(config.max_retry_count),
            "retry_delay_minutes": str(config.retry_delay_minutes),
            "auto_remove_gmail_label": str(config.auto_remove_gmail_label),
        }
        for key, value in defaults.items():
            if session.get(Setting, key) is None:
                session.add(Setting(key=key, value=value))

