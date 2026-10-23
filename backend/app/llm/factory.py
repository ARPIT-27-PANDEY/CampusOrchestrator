"""Construct the configured LLM provider. No silent fallback to another model."""

from __future__ import annotations

from ..config import Settings
from .base import LLMProvider
from .groq import GroqProvider
from .mock import MockProvider


def build_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "mock":
        return MockProvider()
    return GroqProvider(
        api_key=settings.groq_api_key.get_secret_value() if settings.groq_api_key else None,
        model=settings.groq_model,
        base_url=settings.groq_base_url,
        temperature=settings.groq_temperature,
        max_completion_tokens=settings.groq_max_completion_tokens,
        reasoning_effort=settings.groq_reasoning_effort,
        include_reasoning=settings.groq_include_reasoning,
        stream=settings.groq_stream,
        timeout_s=settings.groq_timeout_s,
        max_retries=settings.groq_max_retries,
    )
