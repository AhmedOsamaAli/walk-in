"""Builds the optional AI provider from settings, so the server and scripts configure it the same way."""
from __future__ import annotations

from .config import Settings
from .llm import LLM, Provider


def build_llm(settings: Settings) -> LLM:
    """The main provider's chain, then Groq's models when a Groq key is set."""
    groq = Provider(
        settings.groq_api_key, settings.groq_base_url, settings.groq_models,
        reasoning_effort=settings.groq_reasoning_effort, token_limit=settings.groq_token_limit,
    )
    return LLM(
        settings.llm_api_key,
        settings.llm_base_url,
        settings.llm_model,
        temperature=settings.llm_temperature,
        reasoning_effort=settings.llm_reasoning_effort,
        fallback_models=settings.llm_fallback_models,
        timeout=settings.llm_timeout,
        also=[groq],
        max_wait=settings.llm_max_wait,
    )
