# LeadFlow AI

LeadFlow AI is a Flask and SQLite email follow-up automation platform for Gmail-labeled conversations. Gmail is used only for reading labels, messages, threads, and replies. All outbound email is sent through SMTP.

## Features

- Gmail label import from `Follow Up`
- Duplicate-safe lead creation by thread and message ID
- Unlimited administrator-managed follow-up steps
- SMTP sending with `Message-ID`, `In-Reply-To`, and `References` threading
- Gmail reply detection that immediately stops all future follow-ups
- Business-hour scheduling with timezone and weekday controls
- Dark Bootstrap dashboard with leads, templates, sequences, settings, logs, statistics, exports, and health pages
- Desktop, sound, console, and dashboard notifications
- SQLite backups with 30-backup retention
- Structured logs plus rotating daily file logs
- CSV exports for all, replied, pending, completed, failed, and paused leads
- AI provider interface for future personalization, summarization, extraction, sentiment, and send-time suggestions

## Quick Start

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your dashboard password, SMTP credentials, timezone, and Gmail OAuth paths.

Create a Google Cloud OAuth desktop client with Gmail API enabled, download it as `credentials.json`, and place it beside this README or point `GMAIL_CREDENTIALS_FILE` to its path. The first Gmail action will open the OAuth browser flow and create `token.json`.

Run locally:

```bash
python -m leadflow_ai.app
```

Open `http://localhost:5000` and sign in with the configured dashboard credentials.

Run with Gunicorn:

```bash
gunicorn -w 2 -b 0.0.0.0:5000 "leadflow_ai.app:app"
```

For production, use one scheduler process only. If running multiple Gunicorn workers, start the web app with a single scheduler owner or move scheduled jobs to a separate process.

## Gmail and SMTP Notes

LeadFlow AI never sends through Gmail API. SMTP must be configured separately. For Gmail SMTP, use an app password on accounts with two-factor authentication.

The Gmail label name defaults to `Follow Up`. Every thread inside that label can become a lead. Replies are detected by scanning existing imported thread IDs for external messages newer than the last outbound send.

## Project Layout

```text
leadflow_ai/
  app.py
  config.py
  database.py
  models.py
  scheduler.py
  gmail_client.py
  smtp_client.py
  reply_detector.py
  template_engine.py
  dashboard.py
  notifications.py
  logging_manager.py
  backup_manager.py
  health_monitor.py
  utils.py
  ai_provider.py
  templates/
  static/
  logs/
  backups/
  database/
```

## Security

The dashboard includes password login, session timeout, CSRF tokens on mutating forms, secure cookie flags, rate limiting, input validation through controlled form handling, and SQLAlchemy prepared statements. Set a strong `SECRET_KEY` and dashboard password before deployment.

## Operations

Recurring jobs:

- Import Gmail leads every configured interval
- Detect replies every minute
- Send due emails every minute
- Retry failed emails every 15 minutes
- Cleanup logs nightly
- Backup database nightly
- Health check every 10 minutes

Backups are written to `leadflow_ai/backups/` and the newest 30 are retained.

