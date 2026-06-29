"""Jinja2 email template rendering."""

from __future__ import annotations

from dataclasses import dataclass

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateError, select_autoescape

from .config import config
from .database import session_scope
from .models import Lead, Template


@dataclass(frozen=True)
class RenderedEmail:
    """Rendered email content."""

    subject: str
    html: str
    text: str


class EmailTemplateEngine:
    """Render database and filesystem templates with lead variables."""

    def __init__(self) -> None:
        self.environment = Environment(
            loader=FileSystemLoader(str(config.email_templates_dir)),
            autoescape=select_autoescape(["html", "xml"]),
            undefined=StrictUndefined,
        )

    def context_for_lead(self, lead: Lead) -> dict[str, str]:
        """Build Jinja context for a lead."""
        return {
            "name": lead.name or "there",
            "company": lead.company or "",
            "website": lead.website or "",
            "service": lead.service or "LeadFlow AI",
            "industry": lead.industry or "",
            "city": lead.city or "",
            "custom": lead.custom or "",
            "subject": lead.subject or "",
            "email": lead.email,
        }

    def render_string(self, template_source: str, context: dict[str, str]) -> str:
        """Render a Jinja template string."""
        try:
            return self.environment.from_string(template_source).render(**context)
        except TemplateError as exc:
            raise ValueError(f"Template rendering failed: {exc}") from exc

    def render(self, template_name: str, lead: Lead) -> RenderedEmail:
        """Render a named database template for a lead."""
        with session_scope() as session:
            template = session.query(Template).filter_by(name=template_name, enabled=True).one_or_none()
            if template is None:
                raise ValueError(f"Template '{template_name}' does not exist or is disabled")
            session.expunge(template)
        context = self.context_for_lead(lead)
        return RenderedEmail(
            subject=self.render_string(template.subject, context),
            html=self.render_string(template.html_body, context),
            text=self.render_string(template.text_body, context),
        )


template_engine = EmailTemplateEngine()

