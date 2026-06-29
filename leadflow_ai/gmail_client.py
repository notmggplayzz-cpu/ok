"""Gmail API client for reading labels, messages, and threads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .config import config
from .logging_manager import log_event
from .utils import decode_gmail_body, extract_email, extract_name, guess_company, header_value

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.modify"]


@dataclass(frozen=True)
class GmailMessage:
    """Normalized Gmail message."""

    gmail_id: str
    thread_id: str
    message_id: str
    subject: str
    sender: str
    sender_email: str
    sender_name: str
    date: str
    body: str
    references: str
    in_reply_to: str
    internal_date: datetime


class GmailClient:
    """Read-only Gmail API wrapper used for imports and reply detection."""

    def __init__(self) -> None:
        self.service = None

    def authenticate(self):
        """Authenticate with Gmail and return a service client."""
        if self.service is not None:
            return self.service
        token_path = Path(config.gmail_token_file)
        credentials_path = Path(config.gmail_credentials_file)
        creds = None
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not credentials_path.exists():
                    raise FileNotFoundError(
                        f"Gmail credentials file not found: {credentials_path}. "
                        "Create it from Google Cloud OAuth credentials."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
                creds = flow.run_local_server(port=0)
            token_path.write_text(creds.to_json(), encoding="utf-8")
        self.service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return self.service

    def _service(self):
        return self.authenticate()

    def get_label_id(self, label_name: str) -> str | None:
        """Return Gmail label ID by display name."""
        labels = self._service().users().labels().list(userId="me").execute().get("labels", [])
        for label in labels:
            if label.get("name") == label_name:
                return label.get("id")
        return None

    def list_thread_ids_for_label(self, label_name: str) -> list[str]:
        """List all thread IDs currently in a Gmail label."""
        label_id = self.get_label_id(label_name)
        if not label_id:
            log_event("warning", "gmail", f"Label '{label_name}' not found")
            return []
        thread_ids: list[str] = []
        request = self._service().users().threads().list(userId="me", labelIds=[label_id], maxResults=100)
        while request is not None:
            response = request.execute()
            thread_ids.extend(item["id"] for item in response.get("threads", []))
            request = self._service().users().threads().list_next(request, response)
        return thread_ids

    def get_thread_messages(self, thread_id: str) -> list[GmailMessage]:
        """Return normalized messages for a Gmail thread."""
        thread = self._service().users().threads().get(userId="me", id=thread_id, format="full").execute()
        return [self._normalize(message) for message in thread.get("messages", [])]

    def remove_label_from_thread(self, thread_id: str, label_name: str) -> None:
        """Remove the import label from a thread when configured."""
        label_id = self.get_label_id(label_name)
        if label_id:
            self._service().users().threads().modify(
                userId="me",
                id=thread_id,
                body={"removeLabelIds": [label_id]},
            ).execute()

    def _normalize(self, message: dict) -> GmailMessage:
        headers = message.get("payload", {}).get("headers", [])
        sender = header_value(headers, "From")
        internal_ms = int(message.get("internalDate", "0") or 0)
        return GmailMessage(
            gmail_id=message.get("id", ""),
            thread_id=message.get("threadId", ""),
            message_id=header_value(headers, "Message-ID") or message.get("id", ""),
            subject=header_value(headers, "Subject"),
            sender=sender,
            sender_email=extract_email(sender),
            sender_name=extract_name(sender),
            date=header_value(headers, "Date"),
            body=decode_gmail_body(message.get("payload", {})),
            references=header_value(headers, "References"),
            in_reply_to=header_value(headers, "In-Reply-To"),
            internal_date=datetime.utcfromtimestamp(internal_ms / 1000) if internal_ms else datetime.utcnow(),
        )

    def first_external_message(self, thread_id: str, own_email: str) -> GmailMessage | None:
        """Return the first message in a thread not sent by the configured SMTP account."""
        messages = self.get_thread_messages(thread_id)
        for message in messages:
            if message.sender_email.lower() != own_email.lower():
                return message
        return messages[0] if messages else None

    def external_replies_after(self, thread_id: str, own_email: str, after: datetime | None) -> Iterable[GmailMessage]:
        """Yield external messages in a thread after a timestamp."""
        for message in self.get_thread_messages(thread_id):
            if message.sender_email.lower() == own_email.lower():
                continue
            if after is not None and message.internal_date <= after:
                continue
            yield message


gmail_client = GmailClient()

