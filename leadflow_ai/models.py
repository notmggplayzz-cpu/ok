"""SQLAlchemy models for LeadFlow AI."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class LeadStatus(StrEnum):
    """Supported lead lifecycle states."""

    PENDING = "pending"
    WAITING = "waiting"
    REPLIED = "replied"
    COMPLETED = "completed"
    PAUSED = "paused"
    FAILED = "failed"


class Lead(Base):
    """A Gmail thread imported as an outreach lead."""

    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("thread_id", name="uq_leads_thread_id"),
        Index("ix_leads_email", "email"),
        Index("ix_leads_thread_id", "thread_id"),
        Index("ix_leads_status", "status"),
        Index("ix_leads_next_scheduled_time", "next_scheduled_followup"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(255), nullable=False)
    message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    gmail_message_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    subject: Mapped[str] = mapped_column(String(500), default="")
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    name: Mapped[str] = mapped_column(String(255), default="")
    company: Mapped[str] = mapped_column(String(255), default="")
    website: Mapped[str] = mapped_column(String(500), default="")
    service: Mapped[str] = mapped_column(String(255), default="LeadFlow AI")
    industry: Mapped[str] = mapped_column(String(255), default="")
    city: Mapped[str] = mapped_column(String(255), default="")
    custom: Mapped[str] = mapped_column(Text, default="")
    date_added: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    current_stage: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default=LeadStatus.PENDING.value, nullable=False)
    next_scheduled_followup: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_sent_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reply_status: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reply_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reply_body: Mapped[str] = mapped_column(Text, default="")
    reply_sender: Mapped[str] = mapped_column(String(320), default="")
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str] = mapped_column(Text, default="")
    original_references: Mapped[str] = mapped_column(Text, default="")
    last_outbound_message_id: Mapped[str] = mapped_column(String(255), default="")

    activities: Mapped[list["ActivityHistory"]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="lead", cascade="all, delete-orphan")


class Template(Base):
    """Reusable Jinja2 email template."""

    __tablename__ = "templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    html_body: Mapped[str] = mapped_column(Text, nullable=False)
    text_body: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FollowUpSequence(Base):
    """Administrator-managed follow-up step."""

    __tablename__ = "follow_up_sequence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    step_number: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    delay_days: Mapped[int] = mapped_column(Integer, nullable=False)
    template_name: Mapped[str] = mapped_column(String(100), ForeignKey("templates.name"), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class LogEntry(Base):
    """Structured log entry displayed in the dashboard."""

    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class Setting(Base):
    """Key-value application setting."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class Notification(Base):
    """Notification sent to the desktop/user."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    lead: Mapped[Lead | None] = relationship(back_populates="notifications")


class ActivityHistory(Base):
    """Auditable activity stream for each lead."""

    __tablename__ = "activity_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    lead: Mapped[Lead | None] = relationship(back_populates="activities")

