"""Optional LLM layer over any OpenAI-compatible endpoint (OpenAI, Azure OpenAI v1, Gemini, Groq, OpenRouter...)."""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from openai import AsyncOpenAI

ToolHandler = Callable[[dict], Awaitable[Any]]
OnToolCall = Callable[[str, dict, str | None], Awaitable[None]]


class LLM:
    def __init__(self, api_key: str, base_url: str | None, model: str, image_model: str | None) -> None:
        self.enabled = bool(api_key)
        self.model = model
        self.image_model = image_model if self.enabled else None
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url) if self.enabled else None

    async def json(self, system: str, user: str, temperature: float = 0.5) -> dict:
        response = await self._client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
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
                model=self.model, messages=messages, tools=tools, temperature=0.5
            )
            message = response.choices[0].message
            if not message.tool_calls:
                messages.append({"role": "assistant", "content": message.content or ""})
                messages.append({"role": "user", "content": f"Keep using the tools and finish by calling {final_tool}."})
                continue
            messages.append({
                "role": "assistant",
                "content": message.content,
                "tool_calls": [call.model_dump() for call in message.tool_calls],
            })
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

    async def image(self, prompt: str) -> str | None:
        if not self.image_model:
            return None
        result = await self._client.images.generate(model=self.image_model, prompt=prompt, size="1024x1024", n=1)
        item = result.data[0]
        if getattr(item, "b64_json", None):
            return f"data:image/png;base64,{item.b64_json}"
        return getattr(item, "url", None)


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
