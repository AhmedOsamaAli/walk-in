"""Optional LLM layer over any OpenAI-compatible chat endpoint.

Tested shape: Google Gemini's OpenAI-compatible endpoint (free tier), OpenAI, Groq, OpenRouter, Azure OpenAI v1.
Nothing here is required: without LLM_API_KEY the app runs on deterministic evidence rules.
"""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

import httpx
from openai import AsyncOpenAI, BadRequestError

ToolHandler = Callable[[dict], Awaitable[Any]]
OnToolCall = Callable[[str, dict, str | None], Awaitable[None]]


class LLM:
    def __init__(
        self,
        api_key: str,
        base_url: str | None,
        model: str,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.enabled = bool(api_key)
        self.model = model
        self.temperature = temperature
        self.reasoning_effort = reasoning_effort
        self._client = (
            AsyncOpenAI(api_key=api_key, base_url=base_url, http_client=http_client, max_retries=2, timeout=60)
            if self.enabled else None
        )

    def _options(self) -> dict:
        options: dict[str, Any] = {}
        if self.temperature is not None:
            options["temperature"] = self.temperature
        if self.reasoning_effort:
            options["reasoning_effort"] = self.reasoning_effort
        return options

    async def json(self, system: str, user: str) -> dict:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        try:
            response = await self._client.chat.completions.create(
                model=self.model, messages=messages, response_format={"type": "json_object"}, **self._options()
            )
        except BadRequestError:
            # Some providers reject response_format; the prompt still asks for JSON.
            response = await self._client.chat.completions.create(model=self.model, messages=messages, **self._options())
        return parse_json(response.choices[0].message.content)

    async def run_tools(
        self,
        system: str,
        user: str,
        tools: list[dict],
        handlers: dict[str, ToolHandler],
        final_tool: str,
        max_steps: int = 8,
        on_call: OnToolCall | None = None,
    ) -> dict | None:
        """Tool-calling loop. Returns the arguments of `final_tool`, or None if the model never calls it."""
        messages: list[dict] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        for _ in range(max_steps):
            response = await self._client.chat.completions.create(
                model=self.model, messages=messages, tools=tools, **self._options()
            )
            message = response.choices[0].message
            if not message.tool_calls:
                messages.append({"role": "assistant", "content": message.content or ""})
                messages.append({"role": "user", "content": f"Keep using the tools and finish by calling {final_tool}."})
                continue
            messages.append(assistant_turn(message))
            for call in message.tool_calls:
                name = call.function.name
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                if on_call:
                    await on_call(name, args, message.content)
                if name == final_tool:
                    return args
                handler = handlers.get(name)
                result = await handler(args) if handler else {"error": f"Unknown tool {name}"}
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, ensure_ascii=False)[:8000],
                })
        return None


def assistant_turn(message) -> dict:
    """Echo an assistant tool-call turn back, keeping provider extras (Gemini returns thought signatures there)."""
    turn: dict[str, Any] = {"role": "assistant", "content": message.content}
    turn["tool_calls"] = [call.model_dump(exclude_none=True) for call in message.tool_calls]
    turn.update(message.model_extra or {})
    return turn


def parse_json(text: str | None) -> dict:
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
    return {}
