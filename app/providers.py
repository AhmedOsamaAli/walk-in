"""Builds the optional AI providers from settings, so the server and scripts configure them the same way.

The chain: the main provider's models (LLM_API_KEY, LLM_MODEL, LLM_FALLBACK_MODELS), then Groq's (GROQ_API_KEY), then any
providers LLM_EXTRA_PROVIDERS lists, in its order. A provider without a key is left out, so adding one needs no code:
its entry in LLM_EXTRA_PROVIDERS, then its key in the variable the entry names.
"""
from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from typing import Any

from .config import Settings
from .llm import LLM, Provider

log = logging.getLogger("walkin")


def build_llm(settings: Settings) -> LLM:
    """The main provider's chain, then Groq's models when a Groq key is set, then the extra providers with keys."""
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
        also=[groq, *extra_providers(settings.llm_extra_providers)],
        max_wait=settings.llm_max_wait,
        wait_budget=settings.agent_wait_budget,
    )


def extra_providers(spec: str, environ: Mapping[str, str] = os.environ) -> list[Provider]:
    """The providers LLM_EXTRA_PROVIDERS lists (a JSON list), each once the variable its "key_env" names holds a key.
    An entry that cannot be read is left out, and the log says why; nothing here stops the server from starting."""
    if not spec.strip():
        return []
    try:
        entries = json.loads(spec)
    except ValueError:
        log.warning("LLM_EXTRA_PROVIDERS is not JSON, so no extra AI provider is used")
        return []
    if not isinstance(entries, list):
        log.warning("LLM_EXTRA_PROVIDERS must be a JSON list of providers, so no extra AI provider is used")
        return []
    providers = []
    for number, entry in enumerate(entries, 1):
        name = entry.get("name") if isinstance(entry, dict) and isinstance(entry.get("name"), str) else f"#{number}"
        try:
            provider = provider_of(entry, environ)
        except (TypeError, ValueError) as exc:
            log.warning("Extra AI provider %s is left out: %s", name, exc)
            continue
        if provider is None:
            log.info("Extra AI provider %s is off: its key variable is empty", name)
            continue
        log.info("Extra AI provider %s: %d models after the others", name, len(provider.models))
        providers.append(provider)
    return providers


def provider_of(entry: Any, environ: Mapping[str, str]) -> Provider | None:
    """One LLM_EXTRA_PROVIDERS entry as a Provider; None while its key variable is empty. ValueError or TypeError say
    what is wrong with it."""
    if not isinstance(entry, dict):
        raise TypeError("an entry must be a JSON object")
    base_url, key_env, models = entry.get("base_url"), entry.get("key_env"), entry.get("models")
    if not isinstance(base_url, str) or not base_url.startswith(("https://", "http://")):
        raise ValueError('"base_url" must be the endpoint\'s http(s) URL')
    if not isinstance(key_env, str) or not key_env.strip():
        raise ValueError('"key_env" must name the environment variable that holds the key')
    if isinstance(models, str):
        models = models.split(",")
    if not isinstance(models, list) or not all(isinstance(model, str) for model in models):
        raise ValueError('"models" must be a list of model names')
    models = tuple(model.strip() for model in models if model.strip())
    if not models:
        raise ValueError('"models" lists no model')
    token_limit, effort, temperature = entry.get("token_limit"), entry.get("reasoning_effort"), entry.get("temperature")
    if token_limit is not None and (not isinstance(token_limit, int) or isinstance(token_limit, bool) or token_limit <= 0):
        raise ValueError('"token_limit" must be a positive whole number')
    if effort is not None and not isinstance(effort, str):
        raise ValueError('"reasoning_effort" must be text')
    if temperature is not None and (not isinstance(temperature, int | float) or isinstance(temperature, bool)):
        raise ValueError('"temperature" must be a number')
    key = environ.get(key_env.strip(), "").strip()
    if not key:
        return None
    return Provider(key, base_url.rstrip("/"), models, temperature=temperature, reasoning_effort=effort or None,
                    token_limit=token_limit)
