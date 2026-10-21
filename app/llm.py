"""Optional LLM layer over any OpenAI-compatible chat endpoint.

Tested shape: Google Gemini's OpenAI-compatible endpoint (free tier), OpenAI, Groq, OpenRouter, Azure OpenAI v1.
Nothing here is required: without LLM_API_KEY the app runs on deterministic evidence rules.

Free tiers are small (Gemini: a handful of requests per minute and a few dozen per day, for each model), so every
call walks a chain of models. A model that is rate limited, overloaded or hanging rests for a while and the next
one answers; a tool-calling conversation stays on one model for as long as it can.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Awaitable, Callable

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, BadRequestError

log = logging.getLogger("blankspace")

ToolHandler = Callable[[dict], Awaitable[Any]]
OnToolCall = Callable[[str, dict, str | None], Awaitable[None]]
OnStep = Callable[[int, str], Awaitable[None]]

# Google's documented value for continuing a conversation on a model that did not sign its earlier turns.
SIGNATURE_SENTINEL = "skip_thought_signature_validator"

# How long a model rests after a failure before it is tried again, in seconds.
REST_NETWORK = 10.0
REST_OVERLOADED = 120.0
REST_HANGING = 300.0
REST_DAILY_QUOTA = 3600.0
REST_NOT_OFFERED = 6 * 3600.0
MAX_RETRY_DELAY = 300.0


class LLMUnavailable(RuntimeError):
    """Every configured model is resting after rate limits, overload or errors."""


class LLM:
    def __init__(
        self,
        api_key: str,
        base_url: str | None,
        model: str,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        fallback_models: tuple[str, ...] | list[str] = (),
        timeout: float = 60.0,
        first_reply_timeout: float = 25.0,
    ) -> None:
        self.enabled = bool(api_key)
        self.model = model
        self.models = list(dict.fromkeys(name.strip() for name in [model, *fallback_models] if name and name.strip()))
        self.temperature = temperature
        self.reasoning_effort = reasoning_effort
        self.timeout = timeout
        # The first reply of a tool conversation is short (tool calls only); waiting long means the model is stuck.
        self.first_reply_timeout = first_reply_timeout
        self._resting: dict[str, float] = {}
        self._client = (
            AsyncOpenAI(api_key=api_key, base_url=base_url, http_client=http_client, max_retries=0, timeout=timeout)
            if self.enabled else None
        )

    def resting(self) -> dict[str, int]:
        """Models currently resting, with the seconds left."""
        now = time.monotonic()
        return {model: round(until - now) for model, until in self._resting.items() if until > now}

    def _options(self) -> dict:
        options: dict[str, Any] = {}
        if self.temperature is not None:
            options["temperature"] = self.temperature
        if self.reasoning_effort:
            options["reasoning_effort"] = self.reasoning_effort
        return options

    def _candidates(self, prefer: str | None) -> list[str]:
        order = [prefer, *(m for m in self.models if m != prefer)] if prefer in self.models else self.models
        now = time.monotonic()
        return [model for model in order if self._resting.get(model, 0.0) <= now]

    async def _create(self, messages: list[dict], *, prefer: str | None = None, timeout: float | None = None, **kwargs):
        """One completion from the first model that answers. Returns (response, model)."""
        failures: list[str] = []
        for model in self._candidates(prefer):
            sent = messages if prefer in (None, model) else neutralize_signatures(messages, model)
            try:
                response = await self._client.chat.completions.create(
                    model=model, messages=sent, timeout=timeout or self.timeout, **self._options(), **kwargs
                )
            except (APIConnectionError, APIStatusError) as exc:
                rest = rest_seconds(exc)
                if rest is None:
                    raise
                self._resting[model] = time.monotonic() + rest
                failures.append(f"{model}: {describe(exc)}")
                log.warning("LLM model %s rests %.0fs after %s", model, rest, describe(exc))
                continue
            if not response.choices:
                self._resting[model] = time.monotonic() + REST_NETWORK
                failures.append(f"{model}: empty response")
                continue
            return response, model
        raise LLMUnavailable("; ".join(failures) or "every model is resting after rate limits or errors")

    async def complete_json(self, system: str, user: str) -> tuple[dict, str]:
        """A JSON answer and the model that gave it."""
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        try:
            response, model = await self._create(messages, response_format={"type": "json_object"})
        except BadRequestError:
            # Some providers reject response_format; the prompt still asks for JSON.
            response, model = await self._create(messages)
        return parse_json(response.choices[0].message.content), model

    async def run_tools(
        self,
        system: str,
        user: str,
        tools: list[dict],
        handlers: dict[str, ToolHandler],
        final_tool: str,
        max_steps: int = 8,
        on_call: OnToolCall | None = None,
        on_step: OnStep | None = None,
    ) -> tuple[dict | None, str | None]:
        """Tool-calling loop. Returns the arguments of `final_tool` (None if the model never calls it) and the model
        that finished the conversation. Tool calls from one model turn run concurrently.
        """
        messages: list[dict] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        model: str | None = None
        for step in range(max_steps):
            if on_step:
                await on_step(step, "start")
            try:
                response, used = await self._create(
                    messages, prefer=model, tools=tools, timeout=self.first_reply_timeout if step == 0 else None
                )
            except Exception:
                if on_step:
                    await on_step(step, "failed")
                raise
            if on_step:
                await on_step(step, "end")
            if model and used != model:
                messages = neutralize_signatures(messages, used)
            model = used
            message = response.choices[0].message
            if not message.tool_calls:
                messages.append({"role": "assistant", "content": message.content or ""})
                messages.append({"role": "user", "content": f"Keep using the tools and finish by calling {final_tool}."})
                continue
            messages.append(assistant_turn(message))
            calls = [(call, call_arguments(call)) for call in message.tool_calls]
            if on_call:
                for call, args in calls:
                    await on_call(call.function.name, args, message.content)
            final = next((args for call, args in calls if call.function.name == final_tool), None)
            if final is not None:
                return final, model
            results = await asyncio.gather(*(run_tool(handlers, call.function.name, args) for call, args in calls))
            for (call, _), result in zip(calls, results):
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, ensure_ascii=False)[:8000],
                })
        return None, model


async def run_tool(handlers: dict[str, ToolHandler], name: str, args: dict) -> Any:
    handler = handlers.get(name)
    if handler is None:
        return {"error": f"Unknown tool {name}"}
    try:
        return await handler(args)
    except Exception as exc:  # one failing tool should not end the investigation
        log.warning("Tool %s failed", name, exc_info=True)
        return {"error": f"{name} failed ({type(exc).__name__})"}


def call_arguments(call) -> dict:
    try:
        args = json.loads(call.function.arguments or "{}")
    except json.JSONDecodeError:
        return {}
    return args if isinstance(args, dict) else {}


def rest_seconds(exc: Exception) -> float | None:
    """How long a model should rest after this failure; None when any other model would fail the same way."""
    if isinstance(exc, APITimeoutError):
        return REST_HANGING
    if isinstance(exc, APIConnectionError):
        return REST_NETWORK
    if not isinstance(exc, APIStatusError):
        return None
    if exc.status_code == 429:
        text = str(exc)
        if "PerDay" in text:
            return REST_DAILY_QUOTA
        delay = re.search(r"retry in ([\d.]+)\s*s", text) or re.search(r"retryDelay\W+([\d.]+)s", text)
        return min(MAX_RETRY_DELAY, float(delay.group(1)) + 1.0) if delay else 60.0
    if exc.status_code in (403, 404):  # the model is not offered to this key
        return REST_NOT_OFFERED
    if exc.status_code >= 500:
        return REST_OVERLOADED
    return None


def describe(exc: Exception) -> str:
    if isinstance(exc, APIStatusError):
        if exc.status_code == 429:
            return "HTTP 429 (daily quota)" if "PerDay" in str(exc) else "HTTP 429 (rate limit)"
        return f"HTTP {exc.status_code}"
    return type(exc).__name__


def neutralize_signatures(messages: list[dict], next_model: str) -> list[dict]:
    """Let another model continue a tool conversation.

    Thought signatures only validate on the model that produced them, so they are replaced with Google's sentinel.
    Gemini models also need a signature on the first call of every tool-calling turn, so one is added there.
    """
    gemini = next_model.lower().startswith("gemini")
    out = []
    for message in messages:
        calls = message.get("tool_calls")
        if message.get("role") != "assistant" or not calls:
            out.append(message)
            continue
        neutral = []
        for index, call in enumerate(calls):
            extra = dict(call.get("extra_content") or {})
            google = dict(extra.get("google") or {})
            if "thought_signature" in google or (gemini and index == 0):
                google["thought_signature"] = SIGNATURE_SENTINEL
                extra["google"] = google
                call = {**call, "extra_content": extra}
            neutral.append(call)
        out.append({**message, "tool_calls": neutral})
    return out


def assistant_turn(message) -> dict:
    """Echo an assistant tool-call turn back, keeping provider extras (Gemini returns thought signatures there)."""
    turn: dict[str, Any] = {"role": "assistant", "content": message.content}
    turn["tool_calls"] = [call.model_dump(exclude_none=True) for call in message.tool_calls]
    turn.update(message.model_extra or {})
    return turn


def parse_json(text: str | None) -> dict:
    """The JSON object in a reply, also when it is wrapped in prose or a code fence; {} when there is none."""
    if not text:
        return {}
    candidates = [text]
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return {}
