"""More AI providers by configuration only (LLM_EXTRA_PROVIDERS, app.providers): after the main chain and Groq, in the
order listed, each off until its key variable holds a key; an entry that cannot be read is left out, never fatal."""
from __future__ import annotations

import json
import logging
from dataclasses import replace

from app import config
from app.providers import build_llm, extra_providers

ONE = {"name": "Example", "base_url": "https://llm.example/v1/", "key_env": "EXAMPLE_LLM_KEY",
       "models": ["example-large", "example-small"], "token_limit": 6000, "reasoning_effort": "low"}
OTHER = {"name": "Other", "base_url": "https://other.example/v1", "key_env": "OTHER_LLM_KEY", "models": "other-a, other-b"}


def settings(**changes) -> config.Settings:
    base = {"llm_api_key": "main-key", "llm_model": "main-model", "llm_fallback_models": ("main-backup",),
            "groq_api_key": "groq-key", "groq_models": ("groq-big",), "llm_extra_providers": "", "agent_wait_budget": 20.0}
    return replace(config.settings, **{**base, **changes})


def test_without_extra_providers_the_chain_is_as_before():
    llm = build_llm(settings())
    assert llm.models == ["main-model", "main-backup", "groq-big"] and llm.wait_budget == 20.0


def test_extra_providers_follow_groq_in_order_once_their_keys_are_set(monkeypatch):
    monkeypatch.setenv("EXAMPLE_LLM_KEY", "example-key")
    monkeypatch.setenv("OTHER_LLM_KEY", "other-key")
    llm = build_llm(settings(llm_extra_providers=json.dumps([ONE, OTHER])))
    assert llm.models == ["main-model", "main-backup", "groq-big", "example-large", "example-small", "other-a", "other-b"]
    route = llm._routes["example-small"]
    assert str(route.client.base_url) == "https://llm.example/v1/" and route.client.api_key == "example-key"
    assert route.token_limit == 6000 and route.options == {"reasoning_effort": "low"}
    assert llm._routes["other-a"].client.api_key == "other-key" and llm._routes["other-a"].token_limit is None


def test_a_provider_without_its_key_is_off(monkeypatch):
    monkeypatch.delenv("EXAMPLE_LLM_KEY", raising=False)
    monkeypatch.setenv("OTHER_LLM_KEY", "other-key")
    providers = extra_providers(json.dumps([ONE, OTHER]))
    assert [provider.models for provider in providers] == [("other-a", "other-b")]


def test_entries_that_cannot_be_read_are_left_out_and_logged(caplog):
    environ = {"EXAMPLE_LLM_KEY": "k", "OTHER_LLM_KEY": "k"}
    with caplog.at_level(logging.INFO, logger="walkin"):
        assert extra_providers("{not json", environ) == []
        assert extra_providers('{"name": "not a list"}', environ) == []
        broken = [{**ONE, "base_url": "ftp://x"}, {**ONE, "models": []}, {**ONE, "key_env": ""}, "text",
                  {**ONE, "token_limit": -1}, {**ONE, "temperature": "warm"}, OTHER]
        assert [p.models for p in extra_providers(json.dumps(broken), environ)] == [("other-a", "other-b")]
    logged = "\n".join(caplog.messages)
    assert "LLM_EXTRA_PROVIDERS is not JSON" in logged and "must be a JSON list" in logged
    assert logged.count("is left out") == 6 and "k" not in [word.strip(",:") for word in logged.split()]  # no key


def test_a_model_already_in_the_chain_keeps_its_first_provider(monkeypatch):
    monkeypatch.setenv("EXAMPLE_LLM_KEY", "example-key")
    llm = build_llm(settings(llm_extra_providers=json.dumps([{**ONE, "models": ["groq-big", "example-large"]}])))
    assert llm.models == ["main-model", "main-backup", "groq-big", "example-large"]
    assert llm._routes["groq-big"].client.api_key == "groq-key"
