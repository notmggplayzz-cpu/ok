"""Desktop, sound, console, and dashboard notifications."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from .config import config
from .database import session_scope
from .models import Notification

if TYPE_CHECKING:
    from .models import Lead


class NotificationManager:
    """Dispatch notifications through available local channels."""

    def notify_reply(self, lead: "Lead", preview: str) -> None:
        """Notify all channels that a reply was received."""
        title = "NEW REPLY RECEIVED"
        body = (
            f"Lead: {lead.name}\nEmail: {lead.email}\nCompany: {lead.company}\n"
            f"Time: {lead.reply_time}\nPreview: {preview[:300]}"
        )
        print(f"\n{title}\n{body}\n", file=sys.stderr)
        with session_scope() as session:
            session.add(Notification(lead_id=lead.id, title=title, body=body))
        if config.notification_enabled:
            try:
                from plyer import notification

                notification.notify(title=title, message=body[:240], app_name="LeadFlow AI", timeout=8)
            except Exception:
                pass
        if config.sound_enabled:
            self._play_sound()

    def _play_sound(self) -> None:
        """Play a lightweight platform sound when possible."""
        try:
            if sys.platform == "darwin":
                import subprocess

                subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"], check=False)
            elif sys.platform.startswith("win"):
                import winsound

                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            else:
                print("\a", end="", file=sys.stderr)
        except Exception:
            pass


notification_manager = NotificationManager()

