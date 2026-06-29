"""SMTP-only outbound email sending with Gmail threading headers."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from .config import config
from .models import Lead
from .template_engine import RenderedEmail
from .utils import make_message_id


class SMTPClient:
    """Send emails using configured SMTP settings."""

    def _connect(self):
        if config.smtp_ssl:
            server = smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=30)
        else:
            server = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=30)
        if config.smtp_tls and not config.smtp_ssl:
            server.starttls()
        if config.smtp_username:
            server.login(config.smtp_username, config.smtp_password)
        return server

    def test_connection(self) -> tuple[bool, str]:
        """Validate SMTP connectivity."""
        try:
            with self._connect() as server:
                server.noop()
            return True, "SMTP connection healthy"
        except Exception as exc:
            return False, str(exc)

    def send_followup(self, lead: Lead, rendered: RenderedEmail) -> str:
        """Send a rendered follow-up and return its outbound Message-ID."""
        message_id = make_message_id(f"{lead.id}-{lead.current_stage}")
        msg = EmailMessage()
        msg["From"] = f"{config.smtp_from_name} <{config.smtp_from_email}>"
        msg["To"] = lead.email
        msg["Subject"] = rendered.subject
        msg["Message-ID"] = message_id
        references = " ".join(part for part in [lead.original_references, lead.message_id, lead.last_outbound_message_id] if part)
        if references:
            msg["References"] = references
        if lead.last_outbound_message_id or lead.message_id:
            msg["In-Reply-To"] = lead.last_outbound_message_id or lead.message_id
        msg.set_content(rendered.text)
        msg.add_alternative(rendered.html, subtype="html")
        with self._connect() as server:
            server.send_message(msg)
        return message_id


smtp_client = SMTPClient()

