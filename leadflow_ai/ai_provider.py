"""Abstract AI personalization extension points."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class AILeadContext:
    """Provider-neutral context for future AI integrations."""

    name: str
    email: str
    company: str
    website: str
    subject: str
    reply_body: str = ""


class AIProvider(ABC):
    """Interface future OpenAI, Anthropic, Gemini, or local providers can implement."""

    @abstractmethod
    def personalize_email(self, context: AILeadContext, template: str) -> str:
        """Return a personalized email body."""

    @abstractmethod
    def summarize_reply(self, context: AILeadContext) -> str:
        """Summarize a client reply."""

    @abstractmethod
    def extract_company_and_website(self, text: str) -> tuple[str, str]:
        """Extract company and website hints from text."""

    @abstractmethod
    def suggest_send_time(self, context: AILeadContext) -> str:
        """Suggest a best send time in provider-specific terms."""

    @abstractmethod
    def analyze_sentiment(self, context: AILeadContext) -> str:
        """Classify reply sentiment."""


class NullAIProvider(AIProvider):
    """No-op provider used until a concrete AI integration is configured."""

    def personalize_email(self, context: AILeadContext, template: str) -> str:
        return template

    def summarize_reply(self, context: AILeadContext) -> str:
        return context.reply_body[:500]

    def extract_company_and_website(self, text: str) -> tuple[str, str]:
        return "", ""

    def suggest_send_time(self, context: AILeadContext) -> str:
        return "business_hours"

    def analyze_sentiment(self, context: AILeadContext) -> str:
        return "unknown"

