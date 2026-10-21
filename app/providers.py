"""Builds the optional AI providers from settings, so the server and scripts configure them the same way."""
from __future__ import annotations

from .config import Settings
from .images import ImageChain, ImageGen
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


def build_images(settings: Settings) -> ImageChain:
    """The image providers IMAGE_PROVIDER lists, in order; each falls back to the next."""
    names = [name.strip().lower() for name in settings.image_provider.split(",") if name.strip()]
    return ImageChain([image_provider(settings, name) for name in dict.fromkeys(names)])


def image_provider(settings: Settings, name: str) -> ImageGen:
    if name == "cloudflare":
        return ImageGen(
            "cloudflare", cf_account_id=settings.cloudflare_account_id, cf_api_token=settings.cloudflare_api_token,
            model=settings.cloudflare_image_model,
        )
    if name == "horde":
        return ImageGen("horde", api_key=settings.ai_horde_api_key, model=settings.ai_horde_model)
    # Gemini renders with the same key as the agent unless a separate image key is set.
    api_key = settings.image_api_key or (settings.llm_api_key if name == "gemini" else "")
    return ImageGen(name, api_key=api_key, base_url=settings.image_base_url, model=settings.image_model)
