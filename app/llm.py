"""Optional LLM layer over OpenAI-compatible chat endpoints.

Tested shapes: Google Gemini's OpenAI-compatible endpoint (free tier), Groq (free tier), OpenAI, OpenRouter, Azure
OpenAI v1. Nothing here is required: without a key the app runs on deterministic evidence rules.

Free tiers are small (Gemini: a handful of requests per minute and a few dozen per day; Groq: 8,000 tokens per minute;
both for each model), so every call walks a chain of models across providers. A model that is rate limited,
overloaded or hanging rests for a while and the next one answers; a tool-calling conversation stays on one model for
as long as it can, and waits briefly when every model is about to come back.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, BadRequestError

log = logging.getLogger("blankspace")

ToolHandler = Callable[[dict], Awaitable[Any]]
OnToolCall = Callable[[str, dict, str | None], Awaitable[None]]
OnStep = Callable[[int, str], Awaitable[None]]
OnWait = Callable[[float, str], Awaitable[None]]

# Google's documented value for continuing a conversation on a model that did not sign its earlier turns.
SIGNATURE_SENTINEL = "skip_thought_signature_validator"
# Marks which model wrote an assistant turn; stripped before anything is sent.
ORIGIN = "_model"

# How long a model rests after a failure before it is tried again, in seconds.
REST_NETWORK = 10.0
REST_OVERLOADED = 120.0
REST_HANGING = 300.0
REST_DAILY_QUOTA = 3600.0
REST_NOT_OFFERED = 6 * 3600.0
MAX_RETRY_DELAY = 300.0

# Token estimates for providers that limit tokens per request: conservative, survey evidence runs ~3.9 chars a token.
CHARS_PER_TOKEN = 3.3
CUT_NOTE = " …[cut to fit the model's token limit]"

DAILY = re.compile(r"PerDay|per day", re.IGNORECASE)
RETRY_AFTER = re.compile(r"(?:retry in|try again in|retryDelay\W+)\s*((?:\d+(?:\.\d+)?(?:ms|h|m|s))+)")
DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")
SECONDS_PER = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}


class LLMUnavailable(RuntimeError):
    """Every configured model is resting after rate limits, overload or errors."""


@dataclass(frozen=True)
class Provider:
    """An OpenAI-compatible endpoint and the models to try on it, in order."""

    api_key: str
    base_url: str | None
    models: tuple[str, ...] = ()
    temperature: float | None = None
    reasoning_effort: str | None = None
    # Tokens one request may carry, for free tiers that count tokens per minute (Groq: 8,000 per model).
    token_limit: int | None = None

    def options(self) -> dict[str, Any]:
        options: dict[str, Any] = {}
        if self.temperature is not None:
            options["temperature"] = self.temperature
        if self.reasoning_effort:
            options["reasoning_effort"] = self.reasoning_effort
        return options


@dataclass(frozen=True)
class Route:
    client: AsyncOpenAI
    options: dict[str, Any]
    token_limit: int | None


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
        also: Sequence[Provider] = (),
        max_wait: float = 0.0,
    ) -> None:
        """The main provider comes from the first arguments; `also` adds providers whose models follow its chain."""
        main = Provider(api_key, base_url, (model, *fallback_models), temperature, reasoning_effort)
        self._routes: dict[str, Route] = {}
        for provider in (main, *also):
            if not provider.api_key:
                continue
            client = AsyncOpenAI(
                api_key=provider.api_key, base_url=provider.base_url, http_client=http_client, max_retries=0,
                timeout=timeout,
            )
            route = Route(client, provider.options(), provider.token_limit)
            for name in provider.models:
                if name and name.strip():
                    self._routes.setdefault(name.strip(), route)
        self.models = list(self._routes)
        self.enabled = bool(self.models)
        self.model = self.models[0] if self.models else model
        self.timeout = timeout
        # The first reply of a tool conversation is short (tool calls only); waiting long means the model is stuck.
        self.first_reply_timeout = first_reply_timeout
        # Longest pause for a resting model to come back before a call gives up; 0 never waits.
        self.max_wait = max_wait
        self._resting: dict[str, float] = {}

    def resting(self) -> dict[str, int]:
        """Models currently resting, with the seconds left."""
        now = time.monotonic()
        return {model: round(until - now) for model, until in self._resting.items() if until > now}

    def _candidates(self, prefer: str | None, skip: set[str]) -> list[str]:
        order = [prefer, *(m for m in self.models if m != prefer)] if prefer in self.models else self.models
        now = time.monotonic()
        return [model for model in order if model not in skip and self._resting.get(model, 0.0) <= now]

    def _next_wake(self, skip: set[str]) -> float | None:
        """When the first model that could still take this request stops resting (monotonic clock)."""
        times = [self._resting.get(model, 0.0) for model in self.models if model not in skip]
        return min(times) if times else None

    async def _create(
        self,
        messages: list[dict],
        *,
        prefer: str | None = None,
        timeout: float | None = None,
        on_wait: OnWait | None = None,
        **kwargs,
    ):
        """One completion from the first model that answers. Returns (response, model)."""
        failures: list[str] = []
        skip: set[str] = set()  # models this request can never fit
        deadline = time.monotonic() + self.max_wait
        while True:
            for model in self._candidates(prefer, skip):
                route = self._routes[model]
                sent = for_model(messages, model)
                if route.token_limit:
                    fitted = fit(sent, kwargs.get("tools"), route.token_limit)
                    if fitted is None:
                        skip.add(model)
                        failures.append(f"{model}: request too long for its token limit")
                        continue
                    sent = fitted
                try:
                    response = await route.client.chat.completions.create(
                        model=model, messages=sent, timeout=timeout or self.timeout, **route.options, **kwargs
                    )
                except (APIConnectionError, APIStatusError) as exc:
                    rest = rest_seconds(exc)
                    if rest is None:
                        raise
                    failures.append(f"{model}: {describe(exc)}")
                    if rest <= 0:
                        skip.add(model)
                        log.warning("LLM model %s skipped after %s", model, describe(exc))
                    else:
                        self._resting[model] = time.monotonic() + rest
                        log.warning("LLM model %s rests %.0fs after %s", model, rest, describe(exc))
                    continue
                if not response.choices:
                    self._resting[model] = time.monotonic() + REST_NETWORK
                    failures.append(f"{model}: empty response")
                    continue
                if response.usage:
                    log.info("LLM %s: %s prompt + %s completion tokens", model, response.usage.prompt_tokens,
                             response.usage.completion_tokens)
                return response, model
            wake = self._next_wake(skip)
            if wake is None or wake > deadline:
                raise LLMUnavailable("; ".join(failures) or "every model is resting after rate limits or errors")
            seconds = max(0.0, wake - time.monotonic()) + 0.05  # timers can fire a little early
            log.info("Every LLM model is resting; waiting %.1fs for the first to come back", seconds)
            if on_wait:
                await on_wait(seconds, "start")
            await asyncio.sleep(seconds)
            if on_wait:
                await on_wait(seconds, "end")

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
        on_wait: OnWait | None = None,
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
                response, model = await self._create(
                    messages, prefer=model, tools=tools, timeout=self.first_reply_timeout if step == 0 else None,
                    on_wait=on_wait,
                )
            except Exception:
                if on_step:
                    await on_step(step, "failed")
                raise
            if on_step:
                await on_step(step, "end")
            message = response.choices[0].message
            if not message.tool_calls:
                messages.append({"role": "assistant", "content": message.content or ""})
                messages.append({"role": "user", "content": f"Keep using the tools and finish by calling {final_tool}."})
                continue
            messages.append(assistant_turn(message, model))
            calls = [(call, call_arguments(call)) for call in message.tool_calls]
            if on_call:
                for call, args in calls:
                    await on_call(call.function.name, args, message.content)
            final = next((args for call, args in calls if call.function.name == final_tool), None)
            if final is not None:
                return final, model
            results = await asyncio.gather(*(run_tool(handlers, call.function.name, args) for call, args in calls))
            for (call, _), result in zip(calls, results, strict=True):
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
    """How long a model should rest after this failure: 0 when this request can never fit the model (the next one
    should try), None when any other model would fail the same way."""
    if isinstance(exc, APITimeoutError):
        return REST_HANGING
    if isinstance(exc, APIConnectionError):
        return REST_NETWORK
    if not isinstance(exc, APIStatusError):
        return None
    text = str(exc)
    if exc.status_code == 429:
        delay = retry_delay(exc)
        if DAILY.search(text):  # Gemini advises a short retry even when the day's quota is spent
            return delay + 1.0 if delay is not None and delay >= 60 else REST_DAILY_QUOTA
        return min(MAX_RETRY_DELAY, delay + 1.0) if delay is not None else 60.0
    if exc.status_code == 413:  # more tokens than the model's per-minute allowance (Groq)
        return 0.0
    if exc.status_code == 400 and "tool_use_failed" in text:  # an open model wrote a malformed tool call
        return REST_NETWORK
    if exc.status_code in (403, 404):  # the model is not offered to this key
        return REST_NOT_OFFERED
    if exc.status_code >= 500:
        return REST_OVERLOADED
    return None


def retry_delay(exc: APIStatusError) -> float | None:
    """The provider's advice on when to try again, in seconds: "retry in 7.5s" (Gemini), "try again in 1m26.4s"
    (Groq) or a Retry-After header."""
    match = RETRY_AFTER.search(str(exc))
    if match:
        return sum(float(amount) * SECONDS_PER[unit] for amount, unit in DURATION_PART.findall(match.group(1)))
    header = exc.response.headers.get("retry-after") if exc.response is not None else None
    try:
        return float(header) if header else None
    except ValueError:
        return None


def describe(exc: Exception) -> str:
    if isinstance(exc, APIStatusError):
        if exc.status_code == 429:
            return "HTTP 429 (daily quota)" if DAILY.search(str(exc)) else "HTTP 429 (rate limit)"
        if exc.status_code == 413:
            return "HTTP 413 (request too large)"
        return f"HTTP {exc.status_code}"
    return type(exc).__name__


def for_model(messages: list[dict], model: str) -> list[dict]:
    """The conversation as `model` should get it: its own turns exactly as it wrote them, other models' turns cut
    down to the standard fields (providers reject each other's extras) and signed for Gemini."""
    out = []
    for message in messages:
        origin = message.get(ORIGIN)
        if origin is None:
            out.append(message)
            continue
        turn = {key: value for key, value in message.items() if key != ORIGIN}
        out.append(turn if origin == model else neutralize_signatures([plain_turn(turn)], model)[0])
    return out


def plain_turn(turn: dict) -> dict:
    """An assistant turn with only the fields every OpenAI-compatible endpoint accepts."""
    plain: dict[str, Any] = {"role": "assistant", "content": turn.get("content")}
    if turn.get("tool_calls"):
        plain["tool_calls"] = [
            {"id": call.get("id"), "type": call.get("type", "function"), "function": call.get("function")}
            for call in turn["tool_calls"]
        ]
    return plain


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


def assistant_turn(message, model: str) -> dict:
    """Echo an assistant tool-call turn back, keeping provider extras (Gemini returns thought signatures there) and
    which model wrote it, so the extras only ever go back to that model."""
    turn: dict[str, Any] = {"role": "assistant", "content": message.content}
    turn["tool_calls"] = [call.model_dump(exclude_none=True) for call in message.tool_calls]
    turn.update(message.model_extra or {})
    turn[ORIGIN] = model
    return turn


def approx_tokens(messages: list[dict], tools: list[dict] | None) -> int:
    size = len(json.dumps(messages, ensure_ascii=False)) + (len(json.dumps(tools, ensure_ascii=False)) if tools else 0)
    return math.ceil(size / CHARS_PER_TOKEN)


def fit(messages: list[dict], tools: list[dict] | None, token_limit: int) -> list[dict] | None:
    """The conversation cut to fit a per-request token limit, with room for growth: reasoning echoes go first, then
    tool results are shortened, oldest first. None when even the shortest version is too long."""
    budget = int(token_limit * 0.9)
    if approx_tokens(messages, tools) <= budget:
        return messages
    out = [
        {key: value for key, value in m.items() if key != "reasoning"} if m.get("role") == "assistant" else m
        for m in messages
    ]
    results = [index for index, m in enumerate(out) if m.get("role") == "tool"]
    for cap in (3000, 1500, 600, 200):
        for index in results:
            if approx_tokens(out, tools) <= budget:
                return out
            content = str(out[index].get("content") or "")
            if len(content) > cap + len(CUT_NOTE):
                out[index] = {**out[index], "content": content[:cap] + CUT_NOTE}
    return out if approx_tokens(out, tools) <= budget else None


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
