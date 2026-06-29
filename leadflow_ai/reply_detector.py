"""Gmail import, reply detection, and follow-up business logic."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import or_

from .config import config
from .database import session_scope
from .gmail_client import GmailMessage, gmail_client
from .logging_manager import log_event
from .models import ActivityHistory, FollowUpSequence, Lead, LeadStatus
from .notifications import notification_manager
from .smtp_client import smtp_client
from .template_engine import template_engine
from .utils import extract_website, guess_company, next_business_time, utcnow


def _settings(session) -> dict[str, str]:
    from .models import Setting

    return {setting.key: setting.value for setting in session.query(Setting).all()}


class LeadImporter:
    """Import Gmail threads from a configured label into leads."""

    def import_from_gmail(self) -> int:
        """Import labeled Gmail threads and return created count."""
        created = 0
        thread_ids = gmail_client.list_thread_ids_for_label(config.gmail_label_name)
        own_email = config.smtp_from_email or config.smtp_username
        for thread_id in thread_ids:
            try:
                message = gmail_client.first_external_message(thread_id, own_email)
                if message is None:
                    continue
                with session_scope() as session:
                    duplicate = (
                        session.query(Lead)
                        .filter(or_(Lead.thread_id == thread_id, Lead.message_id == message.message_id, Lead.email == message.sender_email))
                        .one_or_none()
                    )
                    if duplicate:
                        continue
                    lead = self._lead_from_message(message)
                    session.add(lead)
                    session.flush()
                    self._schedule_next(session, lead)
                    session.add(ActivityHistory(lead_id=lead.id, action="imported", details=f"Imported from Gmail label {config.gmail_label_name}"))
                    created += 1
                if config.auto_remove_gmail_label:
                    gmail_client.remove_label_from_thread(thread_id, config.gmail_label_name)
            except Exception as exc:
                log_event("error", "import", f"Failed importing Gmail thread {thread_id}: {exc}")
        if created:
            log_event("info", "import", f"Imported {created} new lead(s)")
        return created

    def _lead_from_message(self, message: GmailMessage) -> Lead:
        website = extract_website(message.body)
        return Lead(
            thread_id=message.thread_id,
            message_id=message.message_id,
            gmail_message_id=message.gmail_id,
            subject=message.subject,
            email=message.sender_email,
            name=message.sender_name,
            company=guess_company(message.sender_email, message.body),
            website=website,
            status=LeadStatus.WAITING.value,
            original_references=message.references,
        )

    def _schedule_next(self, session, lead: Lead) -> None:
        first_step = (
            session.query(FollowUpSequence)
            .filter_by(enabled=True)
            .order_by(FollowUpSequence.step_number.asc())
            .first()
        )
        if first_step is None:
            lead.status = LeadStatus.COMPLETED.value
            return
        due = utcnow() + timedelta(days=first_step.delay_days)
        lead.next_scheduled_followup = next_business_time(due, _settings(session))


class ReplyDetector:
    """Detect external replies and stop pending follow-ups."""

    def detect_replies(self) -> int:
        """Mark leads as replied when a newer external Gmail message appears."""
        found = 0
        own_email = config.smtp_from_email or config.smtp_username
        with session_scope() as session:
            leads = (
                session.query(Lead)
                .filter(Lead.reply_status.is_(False), Lead.status.in_([LeadStatus.WAITING.value, LeadStatus.PENDING.value, LeadStatus.FAILED.value]))
                .all()
            )
            for lead in leads:
                try:
                    after = lead.last_sent_time or lead.date_added
                    replies = list(gmail_client.external_replies_after(lead.thread_id, own_email, after))
                    replies = [reply for reply in replies if reply.gmail_id != lead.gmail_message_id]
                    if not replies:
                        continue
                    reply = sorted(replies, key=lambda item: item.internal_date)[-1]
                    lead.reply_status = True
                    lead.reply_time = reply.internal_date
                    lead.reply_body = reply.body
                    lead.reply_sender = reply.sender_email
                    lead.status = LeadStatus.REPLIED.value
                    lead.next_scheduled_followup = None
                    session.add(ActivityHistory(lead_id=lead.id, action="reply_detected", details=f"Reply from {reply.sender_email}"))
                    session.flush()
                    notification_manager.notify_reply(lead, reply.body)
                    log_event("info", "reply", f"Reply detected for {lead.email}; follow-ups stopped")
                    found += 1
                except Exception as exc:
                    log_event("error", "reply", f"Reply detection failed for lead {lead.id}: {exc}")
        return found


class FollowUpSender:
    """Send due follow-up sequence emails."""

    def send_due_emails(self) -> int:
        """Send all currently due follow-ups."""
        sent = 0
        now = utcnow()
        with session_scope() as session:
            settings = _settings(session)
            leads = (
                session.query(Lead)
                .filter(
                    Lead.reply_status.is_(False),
                    Lead.status == LeadStatus.WAITING.value,
                    Lead.next_scheduled_followup.is_not(None),
                    Lead.next_scheduled_followup <= now,
                )
                .order_by(Lead.next_scheduled_followup.asc())
                .all()
            )
            for lead in leads:
                adjusted = next_business_time(now, settings)
                if adjusted > now:
                    lead.next_scheduled_followup = adjusted
                    continue
                try:
                    sequence = self._next_sequence(session, lead)
                    if sequence is None:
                        lead.status = LeadStatus.COMPLETED.value
                        lead.next_scheduled_followup = None
                        continue
                    rendered = template_engine.render(sequence.template_name, lead)
                    outbound_id = smtp_client.send_followup(lead, rendered)
                    lead.current_stage = sequence.step_number
                    lead.last_sent_time = utcnow()
                    lead.last_outbound_message_id = outbound_id
                    lead.retry_count = 0
                    lead.last_error = ""
                    self._schedule_following_step(session, lead, settings)
                    session.add(ActivityHistory(lead_id=lead.id, action="sent", details=f"Sent step {sequence.step_number}"))
                    log_event("info", "smtp", f"Sent step {sequence.step_number} to {lead.email}")
                    sent += 1
                except Exception as exc:
                    lead.retry_count += 1
                    lead.last_error = str(exc)
                    if lead.retry_count >= int(settings.get("max_retry_count", config.max_retry_count)):
                        lead.status = LeadStatus.FAILED.value
                    else:
                        lead.next_scheduled_followup = utcnow() + timedelta(minutes=int(settings.get("retry_delay_minutes", config.retry_delay_minutes)))
                    session.add(ActivityHistory(lead_id=lead.id, action="send_failed", details=str(exc)))
                    log_event("error", "smtp", f"Failed sending to {lead.email}: {exc}")
        return sent

    def retry_failed_emails(self) -> int:
        """Move failed leads back to waiting when retry budget remains."""
        restored = 0
        with session_scope() as session:
            settings = _settings(session)
            for lead in session.query(Lead).filter_by(status=LeadStatus.FAILED.value, reply_status=False).all():
                if lead.retry_count < int(settings.get("max_retry_count", config.max_retry_count)):
                    lead.status = LeadStatus.WAITING.value
                    lead.next_scheduled_followup = next_business_time(utcnow(), settings)
                    restored += 1
        return restored

    def send_now(self, lead_id: int) -> None:
        """Send the next step for a single lead immediately."""
        with session_scope() as session:
            lead = session.get(Lead, lead_id)
            if lead is None:
                raise ValueError("Lead not found")
            if lead.reply_status:
                raise ValueError("Lead has already replied")
            lead.status = LeadStatus.WAITING.value
            lead.next_scheduled_followup = utcnow()
        self.send_due_emails()

    def _next_sequence(self, session, lead: Lead) -> FollowUpSequence | None:
        return (
            session.query(FollowUpSequence)
            .filter(FollowUpSequence.enabled.is_(True), FollowUpSequence.step_number > lead.current_stage)
            .order_by(FollowUpSequence.step_number.asc())
            .first()
        )

    def _schedule_following_step(self, session, lead: Lead, settings: dict[str, str]) -> None:
        following = self._next_sequence(session, lead)
        if following is None:
            lead.status = LeadStatus.COMPLETED.value
            lead.next_scheduled_followup = None
            return
        lead.status = LeadStatus.WAITING.value
        due = utcnow() + timedelta(days=following.delay_days)
        lead.next_scheduled_followup = next_business_time(due, settings)


lead_importer = LeadImporter()
reply_detector = ReplyDetector()
followup_sender = FollowUpSender()
