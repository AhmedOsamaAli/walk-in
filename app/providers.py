"""Builds the optional AI providers from settings, so the server and scripts configure them the same way."""
from __future__ import annotations

from .config import Settings
from .images import ImageGen
from .llm import LLM


def build_llm(settings: Settings) -> LLM:
    return LLM(
        settings.llm_api_key,
        settings.llm_base_url,
        settings.llm_model,
        temperature=settings.llm_temperature,
        reasoning_effort=settings.llm_reasoning_effort,
    )


def build_images(settings: Settings) -> ImageGen:
    return ImageGen(
        provider=settings.image_provider,
        cf_account_id=settings.cloudflare_account_id,
        cf_api_token=settings.cloudflare_api_token,
        api_key=settings.image_api_key,
        base_url=settings.image_base_url,
        model=settings.image_model,
    )
