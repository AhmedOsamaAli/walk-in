import asyncio
import json

import httpx

from app.images import ImageGen
from app.llm import LLM


def completion(message: dict) -> dict:
    return {
        "id": "chatcmpl-test", "object": "chat.completion", "created": 0, "model": "test-model",
        "choices": [{"index": 0, "finish_reason": "tool_calls" if message.get("tool_calls") else "stop", "message": message}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def tool_call(call_id: str, name: str, args: dict, signature: str | None = None) -> dict:
    call = {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
    if signature:
        call["extra_content"] = {"google": {"thought_signature": signature}}
    return call


def mock_llm(responses: list[httpx.Response], seen: list[dict]) -> LLM:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return queue.pop(0)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return LLM("test-key", "https://llm.test/v1/", "test-model", reasoning_effort="low", http_client=client)


def test_tool_loop_runs_tools_and_echoes_thought_signatures():
    seen: list[dict] = []
    llm = mock_llm([
        httpx.Response(200, json=completion({
            "role": "assistant", "content": None,
            "tool_calls": [tool_call("c1", "inspect_gap", {"genre": "Wine Bar"}, signature="sig-1")],
        })),
        httpx.Response(200, json=completion({
            "role": "assistant", "content": None,
            "tool_calls": [tool_call("c2", "submit_concepts", {"concepts": [{"genre": "Wine Bar"}]})],
        })),
    ], seen)
    inspected = []

    async def inspect(args):
        inspected.append(args["genre"])
        return {"ok": True}

    result = asyncio.run(llm.run_tools("system", "user", [], {"inspect_gap": inspect}, final_tool="submit_concepts"))

    assert result == {"concepts": [{"genre": "Wine Bar"}]}
    assert inspected == ["Wine Bar"]
    second = seen[1]["messages"]
    assert second[2]["role"] == "assistant"
    assert second[2]["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == "sig-1"
    assert second[3] == {"role": "tool", "tool_call_id": "c1", "content": json.dumps({"ok": True})}
    assert seen[0]["reasoning_effort"] == "low"
    assert "temperature" not in seen[0]


def test_json_falls_back_when_response_format_is_rejected():
    seen: list[dict] = []
    llm = mock_llm([
        httpx.Response(400, json={"error": {"message": "response_format is not supported", "type": "invalid_request_error"}}),
        httpx.Response(200, json=completion({"role": "assistant", "content": 'Here you go: {"name": "Corner Wine"}'})),
    ], seen)
    assert asyncio.run(llm.json("system", "user")) == {"name": "Corner Wine"}
    assert "response_format" in seen[0]
    assert "response_format" not in seen[1]


def test_cloudflare_images_return_a_data_url():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer token"
        assert "flux-1-schnell" in str(request.url)
        return httpx.Response(200, json={"success": True, "result": {"image": "QUJD"}})

    images = ImageGen("cloudflare", "account", "token", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert images.enabled
    assert asyncio.run(images.generate("a cafe interior")) == "data:image/jpeg;base64,QUJD"
    assert not ImageGen("cloudflare", "", "").enabled
