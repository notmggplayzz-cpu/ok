"""General utility helpers."""

from __future__ import annotations

import base64
import email.utils
import hashlib
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .config import config

EMAIL_RE = re.compile(r"[\w.!#$%&'*+/=?^_`{|}~-]+@[\w.-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"https?://[^\s<>)\"]+|www\.[^\s<>)\"]+", re.IGNORECASE)


def utcnow() -> datetime:
    """Return a naive UTC datetime for database storage."""
    return datetime.utcnow()


def extract_email(value: str) -> str:
    """Extract an email address from a header or text value."""
    _, addr = email.utils.parseaddr(value or "")
    if addr:
        return addr.lower()
    match = EMAIL_RE.search(value or "")
    return match.group(0).lower() if match else ""


def extract_name(value: str) -> str:
    """Extract a display name from an email header."""
    name, addr = email.utils.parseaddr(value or "")
    if name:
        return name.strip('" ')
    if addr:
        return addr.split("@", 1)[0].replace(".", " ").title()
    return ""


def extract_website(text: str) -> str:
    """Extract a website URL from text."""
    match = URL_RE.search(text or "")
    return match.group(0).rstrip(".,") if match else ""


def guess_company(email_address: str, text: str = "") -> str:
    """Guess a company name from email domain or body text."""
    ignored = {"gmail", "yahoo", "outlook", "hotmail", "icloud", "proton", "aol"}
    domain = email_address.split("@")[-1].split(".")[0] if "@" in email_address else ""
    if domain and domain.lower() not in ignored:
        return domain.replace("-", " ").title()
    website = extract_website(text)
    if website:
        host = website.replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0]
        return host.split(".")[0].replace("-", " ").title()
    return ""


def decode_gmail_body(payload: dict) -> str:
    """Decode Gmail message body text from a message payload."""
    chunks: list[str] = []

    def walk(part: dict) -> None:
        body = part.get("body", {})
        data = body.get("data")
        mime_type = part.get("mimeType", "")
        if data and ("text/plain" in mime_type or "text/html" in mime_type):
            padded = data + "=" * (-len(data) % 4)
            chunks.append(base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace"))
        for child in part.get("parts", []) or []:
            walk(child)

    walk(payload or {})
    return "\n".join(chunks).strip()


def header_value(headers: list[dict], name: str) -> str:
    """Return a Gmail header value by case-insensitive name."""
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def make_message_id(seed: str) -> str:
    """Build a stable outbound Message-ID."""
    digest = hashlib.sha256(f"{seed}-{utcnow().isoformat()}".encode()).hexdigest()[:24]
    domain = config.smtp_from_email.split("@")[-1] if "@" in config.smtp_from_email else "leadflow.local"
    return f"<{digest}@{domain}>"


def as_bool(value: str | bool | None, default: bool = False) -> bool:
    """Convert setting strings to booleans."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "on"}


def next_business_time(moment: datetime | None = None, settings: dict[str, str] | None = None) -> datetime:
    """Return the next valid business-hour send time as naive UTC."""
    settings = settings or {}
    tz = ZoneInfo(settings.get("business_timezone", config.business_timezone))
    start_hour = int(settings.get("business_start_hour", config.business_start_hour))
    end_hour = int(settings.get("business_end_hour", config.business_end_hour))
    weekdays_only = as_bool(settings.get("weekdays_only"), config.weekdays_only)
    current = (moment or utcnow()).replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)
    if current.hour < start_hour:
        current = current.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    while True:
        if weekdays_only and current.weekday() >= 5:
            current = (current + timedelta(days=1)).replace(hour=start_hour, minute=0, second=0, microsecond=0)
            continue
        if current.hour >= end_hour:
            current = (current + timedelta(days=1)).replace(hour=start_hour, minute=0, second=0, microsecond=0)
            continue
        break
    return current.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

