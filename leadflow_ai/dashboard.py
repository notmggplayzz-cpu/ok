"""Flask dashboard routes for LeadFlow AI."""

from __future__ import annotations

import csv
import io
import secrets
import time
from datetime import datetime
from functools import wraps
from typing import Callable

from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from sqlalchemy import or_

from .backup_manager import backup_manager
from .config import config
from .database import session_scope
from .health_monitor import health_monitor
from .logging_manager import log_event
from .models import ActivityHistory, FollowUpSequence, Lead, LeadStatus, LogEntry, Setting, Template
from .reply_detector import followup_sender, lead_importer, reply_detector
from .scheduler import leadflow_scheduler
from .template_engine import template_engine
from .utils import next_business_time, utcnow

dashboard = Blueprint("dashboard", __name__)
_rate_buckets: dict[str, list[float]] = {}


def login_required(view: Callable):
    """Require an authenticated dashboard session."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("dashboard.login"))
        last_seen = session.get("last_seen", 0)
        if time.time() - last_seen > config.session_timeout_minutes * 60:
            session.clear()
            flash("Session expired. Please sign in again.", "warning")
            return redirect(url_for("dashboard.login"))
        session["last_seen"] = time.time()
        return view(*args, **kwargs)

    return wrapped


def csrf_required(view: Callable):
    """Validate CSRF token for mutating forms."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if request.form.get("csrf_token") != session.get("csrf_token"):
                abort(400, "Invalid CSRF token")
        return view(*args, **kwargs)

    return wrapped


@dashboard.before_app_request
def rate_limit() -> None:
    """Small in-memory rate limiter for dashboard endpoints."""
    if request.endpoint and request.endpoint.startswith("static"):
        return
    key = request.remote_addr or "local"
    now = time.time()
    bucket = [stamp for stamp in _rate_buckets.get(key, []) if now - stamp < 60]
    if len(bucket) >= config.rate_limit_per_minute:
        abort(429)
    bucket.append(now)
    _rate_buckets[key] = bucket


@dashboard.app_context_processor
def inject_globals() -> dict:
    """Expose shared template globals."""
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return {"csrf_token": session["csrf_token"], "LeadStatus": LeadStatus}


@dashboard.route("/login", methods=["GET", "POST"])
@csrf_required
def login():
    """Render and process dashboard login."""
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if secrets.compare_digest(username, config.dashboard_username) and secrets.compare_digest(password, config.dashboard_password):
            session.clear()
            session["authenticated"] = True
            session["last_seen"] = time.time()
            session["csrf_token"] = secrets.token_urlsafe(32)
            log_event("info", "authentication", f"Dashboard login for {username}")
            return redirect(url_for("dashboard.index"))
        flash("Invalid username or password.", "danger")
    return render_template("dashboard/login.html")


@dashboard.route("/logout", methods=["POST"])
@login_required
@csrf_required
def logout():
    """End dashboard session."""
    session.clear()
    return redirect(url_for("dashboard.login"))


@dashboard.route("/")
@login_required
def index():
    """Dashboard overview."""
    with session_scope() as db:
        counts = {status.value: db.query(Lead).filter_by(status=status.value).count() for status in LeadStatus}
        total = db.query(Lead).count()
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        sending_today = db.query(Lead).filter(Lead.next_scheduled_followup >= today_start).count()
        recent = db.query(ActivityHistory).order_by(ActivityHistory.created_at.desc()).limit(12).all()
    return render_template("dashboard/index.html", counts=counts, total=total, sending_today=sending_today, recent=recent)


@dashboard.route("/leads")
@login_required
def leads():
    """Searchable, sortable, paginated lead list."""
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    page = max(int(request.args.get("page", "1")), 1)
    per_page = 25
    with session_scope() as db:
        query = db.query(Lead)
        if q:
            like = f"%{q}%"
            query = query.filter(
                or_(
                    Lead.email.ilike(like),
                    Lead.name.ilike(like),
                    Lead.company.ilike(like),
                    Lead.subject.ilike(like),
                    Lead.website.ilike(like),
                    Lead.status.ilike(like),
                    Lead.reply_body.ilike(like),
                )
            )
        if status:
            query = query.filter_by(status=status)
        total = query.count()
        items = query.order_by(Lead.date_added.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return render_template("dashboard/leads.html", leads=items, q=q, status=status, page=page, per_page=per_page, total=total)


@dashboard.route("/leads/<int:lead_id>")
@login_required
def lead_detail(lead_id: int):
    """Lead detail with activity history."""
    with session_scope() as db:
        lead = db.get(Lead, lead_id)
        if lead is None:
            abort(404)
        activities = db.query(ActivityHistory).filter_by(lead_id=lead_id).order_by(ActivityHistory.created_at.desc()).all()
    return render_template("dashboard/lead_detail.html", lead=lead, activities=activities)


@dashboard.route("/leads/<int:lead_id>/<action>", methods=["POST"])
@login_required
@csrf_required
def lead_action(lead_id: int, action: str):
    """Apply a dashboard action to a lead."""
    with session_scope() as db:
        lead = db.get(Lead, lead_id)
        if lead is None:
            abort(404)
        if action == "pause":
            lead.status = LeadStatus.PAUSED.value
        elif action == "resume":
            lead.status = LeadStatus.WAITING.value
            lead.next_scheduled_followup = next_business_time(utcnow(), _settings(db))
        elif action == "delete":
            db.delete(lead)
        elif action == "retry":
            lead.status = LeadStatus.WAITING.value
            lead.next_scheduled_followup = next_business_time(utcnow(), _settings(db))
            lead.retry_count = 0
        elif action == "send_now":
            lead.next_scheduled_followup = utcnow()
            lead.status = LeadStatus.WAITING.value
        else:
            abort(404)
        if action != "delete":
            db.add(ActivityHistory(lead_id=lead.id, action=action, details="Dashboard action"))
    if action == "send_now":
        followup_sender.send_due_emails()
    flash(f"Lead {action.replace('_', ' ')} complete.", "success")
    return redirect(request.referrer or url_for("dashboard.leads"))


@dashboard.route("/leads/<int:lead_id>/preview")
@login_required
def preview_email(lead_id: int):
    """Preview the next email for a lead."""
    with session_scope() as db:
        lead = db.get(Lead, lead_id)
        if lead is None:
            abort(404)
        sequence = (
            db.query(FollowUpSequence)
            .filter(FollowUpSequence.enabled.is_(True), FollowUpSequence.step_number > lead.current_stage)
            .order_by(FollowUpSequence.step_number.asc())
            .first()
        )
        if sequence is None:
            flash("No remaining follow-up step.", "warning")
            return redirect(url_for("dashboard.lead_detail", lead_id=lead_id))
        db.expunge(lead)
        template_name = sequence.template_name
    rendered = template_engine.render(template_name, lead)
    return render_template("dashboard/preview.html", lead=lead, rendered=rendered)


@dashboard.route("/templates", methods=["GET", "POST"])
@login_required
@csrf_required
def templates():
    """Manage email templates."""
    with session_scope() as db:
        if request.method == "POST":
            template_id = request.form.get("id")
            template = db.get(Template, int(template_id)) if template_id else Template()
            if template is None:
                abort(404)
            template.name = request.form["name"].strip()
            template.subject = request.form["subject"].strip()
            template.html_body = request.form["html_body"]
            template.text_body = request.form["text_body"]
            template.enabled = request.form.get("enabled") == "on"
            db.add(template)
            flash("Template saved.", "success")
        items = db.query(Template).order_by(Template.name.asc()).all()
    return render_template("dashboard/templates.html", templates=items)


@dashboard.route("/sequence", methods=["GET", "POST"])
@login_required
@csrf_required
def sequence():
    """Manage follow-up sequence steps."""
    with session_scope() as db:
        if request.method == "POST":
            step_id = request.form.get("id")
            step = db.get(FollowUpSequence, int(step_id)) if step_id else FollowUpSequence()
            if step is None:
                abort(404)
            step.step_number = int(request.form["step_number"])
            step.delay_days = int(request.form["delay_days"])
            step.template_name = request.form["template_name"]
            step.enabled = request.form.get("enabled") == "on"
            db.add(step)
            flash("Sequence step saved.", "success")
        steps = db.query(FollowUpSequence).order_by(FollowUpSequence.step_number.asc()).all()
        templates_ = db.query(Template).order_by(Template.name.asc()).all()
    return render_template("dashboard/sequence.html", steps=steps, templates=templates_)


@dashboard.route("/settings", methods=["GET", "POST"])
@login_required
@csrf_required
def settings():
    """View and update dashboard settings."""
    keys = [
        "business_start_hour",
        "business_end_hour",
        "business_timezone",
        "weekdays_only",
        "scheduler_interval_minutes",
        "notification_enabled",
        "sound_enabled",
        "theme",
        "max_retry_count",
        "retry_delay_minutes",
        "auto_remove_gmail_label",
    ]
    with session_scope() as db:
        if request.method == "POST":
            for key in keys:
                value = request.form.get(key, "False" if key.endswith("enabled") or key in {"weekdays_only", "auto_remove_gmail_label"} else "")
                setting = db.get(Setting, key) or Setting(key=key, value=value)
                setting.value = value
                db.add(setting)
            flash("Settings saved. Restart the app if scheduler cadence changed.", "success")
        values = {setting.key: setting.value for setting in db.query(Setting).all()}
    return render_template("dashboard/settings.html", settings=values)


@dashboard.route("/logs")
@login_required
def logs():
    """Show structured logs."""
    with session_scope() as db:
        items = db.query(LogEntry).order_by(LogEntry.created_at.desc()).limit(300).all()
    return render_template("dashboard/logs.html", logs=items)


@dashboard.route("/statistics")
@login_required
def statistics():
    """Show lead statistics."""
    with session_scope() as db:
        by_status = {status.value: db.query(Lead).filter_by(status=status.value).count() for status in LeadStatus}
        replies = db.query(Lead).filter_by(reply_status=True).count()
        total = db.query(Lead).count()
        sent = db.query(ActivityHistory).filter_by(action="sent").count()
    rate = round((replies / total) * 100, 1) if total else 0
    return render_template("dashboard/statistics.html", by_status=by_status, total=total, replies=replies, sent=sent, rate=rate)


@dashboard.route("/exports")
@login_required
def exports():
    """Export options page."""
    return render_template("dashboard/exports.html")


@dashboard.route("/exports/<kind>")
@login_required
def export_csv(kind: str):
    """Export leads as CSV."""
    filters = {
        "all": None,
        "replied": LeadStatus.REPLIED.value,
        "pending": LeadStatus.PENDING.value,
        "completed": LeadStatus.COMPLETED.value,
        "failed": LeadStatus.FAILED.value,
        "paused": LeadStatus.PAUSED.value,
    }
    if kind not in filters:
        abort(404)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "thread_id", "message_id", "subject", "email", "name", "company", "website", "date_added", "current_stage", "status", "next_scheduled_followup", "last_sent_time", "reply_status", "reply_time", "reply_sender", "reply_body"])
    with session_scope() as db:
        query = db.query(Lead)
        if filters[kind]:
            query = query.filter_by(status=filters[kind])
        for lead in query.order_by(Lead.date_added.desc()).all():
            writer.writerow([lead.id, lead.thread_id, lead.message_id, lead.subject, lead.email, lead.name, lead.company, lead.website, lead.date_added, lead.current_stage, lead.status, lead.next_scheduled_followup, lead.last_sent_time, lead.reply_status, lead.reply_time, lead.reply_sender, lead.reply_body])
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename=leadflow_{kind}.csv"})


@dashboard.route("/health")
@login_required
def health():
    """Show health checks and scheduler jobs."""
    checks = health_monitor.all_checks(include_external=request.args.get("external") == "1")
    return render_template("dashboard/health.html", checks=checks, jobs=leadflow_scheduler.status())


@dashboard.route("/run/<job>", methods=["POST"])
@login_required
@csrf_required
def run_job(job: str):
    """Run a scheduler job on demand."""
    actions = {
        "import": lead_importer.import_from_gmail,
        "replies": reply_detector.detect_replies,
        "send": followup_sender.send_due_emails,
        "backup": backup_manager.backup_database,
    }
    if job not in actions:
        abort(404)
    result = actions[job]()
    flash(f"Job {job} finished: {result}", "success")
    return redirect(request.referrer or url_for("dashboard.index"))


def _settings(db) -> dict[str, str]:
    return {setting.key: setting.value for setting in db.query(Setting).all()}

