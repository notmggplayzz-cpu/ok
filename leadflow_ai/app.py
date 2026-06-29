"""LeadFlow AI Flask application factory and entrypoint."""

from __future__ import annotations

from datetime import timedelta

from flask import Flask

from .config import config
from .dashboard import dashboard
from .database import init_db
from .logging_manager import log_event
from .scheduler import leadflow_scheduler


def create_app(start_scheduler: bool = True) -> Flask:
    """Create and configure the Flask application."""
    init_db()
    app = Flask(__name__)
    app.secret_key = config.secret_key
    app.permanent_session_lifetime = timedelta(minutes=config.session_timeout_minutes)
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=False,
    )
    app.register_blueprint(dashboard)
    if start_scheduler:
        try:
            leadflow_scheduler.start()
        except Exception as exc:
            log_event("error", "scheduler", f"Scheduler failed to start: {exc}")
    return app


app = create_app(start_scheduler=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

