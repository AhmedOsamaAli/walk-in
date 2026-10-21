import asyncio
import json
import time

import httpx
import pytest

from app.images import ImageGen
from app.llm import SIGNATURE_SENTINEL, LLM, LLMUnavailable, neutralize_signatures, parse_json


def completion(message: dict, model: str = "test-model") -> dict:
    return {
        "id": "chatcmpl-test", "object": "chat.completion", "created": 0, "model": model,
        "choices": [{"index": 0, "finish_reason": "tool_calls" if message.get("tool_calls") else "stop", "message": message}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def tool_call(call_id: str, name: str, args: dict, signature: str | None = None) -> dict:
    call = {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
    if signature:
        call["extra_content"] = {"google": {"thought_signature": signature}}
    return call


def mock_llm(responses: list[httpx.Response], seen: list[dict], fallback_models: tuple[str, ...] = ()) -> LLM:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return queue.pop(0)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return LLM("test-key", "https://llm.test/v1/", "test-model", reasoning_effort="low", http_client=client,
               fallback_models=fallback_models)


def rate_limited(per: str = "Minute", retry: str = "7s") -> httpx.Response:
    return httpx.Response(429, json=[{"error": {
        "code": 429, "status": "RESOURCE_EXHAUSTED",
        "message": f"You exceeded your current quota. Please retry in {retry}.",
        "details": [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                     "violations": [{"quotaId": f"GenerateRequestsPer{per}PerProjectPerModel-FreeTier"}]}],
    }}])


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

    result, model = asyncio.run(llm.run_tools("system", "user", [], {"inspect_gap": inspect}, final_tool="submit_concepts"))

    assert result == {"concepts": [{"genre": "Wine Bar"}]}
    assert model == "test-model"
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
    assert asyncio.run(llm.complete_json("system", "user")) == ({"name": "Corner Wine"}, "test-model")
    assert "response_format" in seen[0]
    assert "response_format" not in seen[1]


def test_a_rate_limited_model_rests_and_the_next_one_answers():
    seen: list[dict] = []
    llm = mock_llm([
        rate_limited("Minute", "7.5s"),
        httpx.Response(200, json=completion({"role": "assistant", "content": '{"ok": 1}'})),
        httpx.Response(200, json=completion({"role": "assistant", "content": '{"ok": 2}'})),
    ], seen, fallback_models=("backup-model",))
    assert asyncio.run(llm.complete_json("system", "user")) == ({"ok": 1}, "backup-model")
    assert [request["model"] for request in seen] == ["test-model", "backup-model"]
    assert 7 <= llm.resting()["test-model"] <= 9  # Google's retry delay, plus a second
    assert asyncio.run(llm.complete_json("system", "user")) == ({"ok": 2}, "backup-model")  # still resting: skipped
    assert seen[-1]["model"] == "backup-model"


def test_a_spent_daily_quota_rests_the_model_for_an_hour():
    llm = mock_llm([rate_limited("Day", "20s"), rate_limited("Minute")], [], fallback_models=("backup-model",))
    with pytest.raises(LLMUnavailable) as error:
        asyncio.run(llm.complete_json("system", "user"))
    assert "daily quota" in str(error.value) and "rate limit" in str(error.value)
    assert llm.resting()["test-model"] > 3500
    assert llm.resting()["backup-model"] < 120


def test_when_every_model_rests_the_call_fails_fast_without_requests():
    seen: list[dict] = []
    llm = mock_llm([httpx.Response(503, json={"error": {"message": "overloaded"}})], seen)
    with pytest.raises(LLMUnavailable):
        asyncio.run(llm.complete_json("system", "user"))
    started = time.perf_counter()
    with pytest.raises(LLMUnavailable):
        asyncio.run(llm.complete_json("system", "user"))
    assert len(seen) == 1 and time.perf_counter() - started < 0.5


def test_a_hanging_model_times_out_and_rests():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body["model"])
        if body["model"] == "test-model":
            raise httpx.ReadTimeout("model is stuck", request=request)
        return httpx.Response(200, json=completion({"role": "assistant", "content": '{"ok": true}'}))

    llm = LLM("key", "https://llm.test/v1/", "test-model", fallback_models=["backup-model"],
              http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert asyncio.run(llm.complete_json("s", "u")) == ({"ok": True}, "backup-model")
    assert calls == ["test-model", "backup-model"] and llm.resting()["test-model"] > 200


def test_request_errors_are_not_hidden_by_the_fallback_chain():
    seen: list[dict] = []
    llm = mock_llm([httpx.Response(401, json={"error": {"message": "bad key"}})], seen, fallback_models=("backup-model",))
    with pytest.raises(Exception) as error:
        asyncio.run(llm.complete_json("system", "user"))
    assert not isinstance(error.value, LLMUnavailable)
    assert len(seen) == 1 and llm.resting() == {}


def test_a_conversation_moves_to_another_model_with_neutral_signatures():
    seen: list[dict] = []
    llm = mock_llm([
        httpx.Response(200, json=completion({"role": "assistant", "content": None, "tool_calls": [
            tool_call("c1", "inspect_gap", {"genre": "Bakery"}, signature="real-signature"),
            tool_call("c2", "inspect_gap", {"genre": "Brunch"}),
        ]})),
        httpx.Response(503, json={"error": {"message": "overloaded"}}),
        httpx.Response(200, json=completion({"role": "assistant", "content": None, "tool_calls": [
            tool_call("c3", "submit_concepts", {"concepts": []}, signature="backup-signature"),
        ]}, model="gemini-backup")),
    ], seen, fallback_models=("gemini-backup",))

    async def inspect(args):
        return {"genre": args["genre"]}

    result, model = asyncio.run(llm.run_tools("s", "u", [], {"inspect_gap": inspect}, final_tool="submit_concepts"))
    assert result == {"concepts": []} and model == "gemini-backup"
    assert [request["model"] for request in seen] == ["test-model", "test-model", "gemini-backup"]
    same_model, other_model = seen[1]["messages"][2]["tool_calls"], seen[2]["messages"][2]["tool_calls"]
    assert same_model[0]["extra_content"]["google"]["thought_signature"] == "real-signature"
    assert other_model[0]["extra_content"]["google"]["thought_signature"] == SIGNATURE_SENTINEL
    assert "extra_content" not in other_model[1]


def test_neutralize_signatures_adds_one_for_gemini_only():
    turn = {"role": "assistant", "content": None, "tool_calls": [tool_call("c1", "x", {}), tool_call("c2", "y", {})]}
    gemini = neutralize_signatures([turn], "gemini-3.6-flash")[0]["tool_calls"]
    assert gemini[0]["extra_content"]["google"]["thought_signature"] == SIGNATURE_SENTINEL
    assert "extra_content" not in gemini[1]
    assert "extra_content" not in neutralize_signatures([turn], "gpt-5")[0]["tool_calls"][0]
    assert "extra_content" not in turn["tool_calls"][0]  # the original history is untouched


def test_tool_calls_of_one_turn_run_concurrently_and_failures_become_results():
    seen: list[dict] = []
    llm = mock_llm([
        httpx.Response(200, json=completion({"role": "assistant", "content": None, "tool_calls": [
            tool_call("a", "slow", {"n": 1}), tool_call("b", "slow", {"n": 2}), tool_call("c", "broken", {}),
        ]})),
        httpx.Response(200, json=completion({"role": "assistant", "content": None, "tool_calls": [
            tool_call("d", "submit", {"done": True}),
        ]})),
    ], seen)

    windows = []

    async def slow(args):
        started = time.perf_counter()
        await asyncio.sleep(0.2)
        windows.append((started, time.perf_counter()))
        return {"n": args["n"]}

    async def broken(args):
        raise ValueError("bug")

    result, _ = asyncio.run(llm.run_tools("s", "u", [], {"slow": slow, "broken": broken}, final_tool="submit"))
    assert result == {"done": True}
    assert max(start for start, _ in windows) < min(end for _, end in windows)  # the two runs overlapped
    results = [m["content"] for m in seen[1]["messages"] if m["role"] == "tool"]
    assert results == ['{"n": 1}', '{"n": 2}', '{"error": "broken failed (ValueError)"}']


def test_parse_json_only_returns_objects():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json("[1, 2]") == {}
    assert parse_json("no json here") == {}
    assert parse_json(None) == {}


def gemini_reply(mime: str = "image/png") -> dict:
    return {"candidates": [{"content": {"parts": [{"text": "Here it is."}, {"inlineData": {"mimeType": mime, "data": "QUJD"}}]}}]}


def test_gemini_renders_wide_images_with_the_agent_key():
    from app.config import Settings
    from app.providers import build_images

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers.get("x-goog-api-key"), json.loads(request.content)))
        return httpx.Response(200, json=gemini_reply())

    images = ImageGen("gemini", api_key="gemini-key", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert images.enabled and images.model == "gemini-3.1-flash-image"
    assert asyncio.run(images.generate("a cafe", "16:9")) == "data:image/png;base64,QUJD"
    url, key, body = seen[0]
    assert url.endswith("/v1beta/models/gemini-3.1-flash-image:generateContent") and key == "gemini-key"
    assert body["generationConfig"] == {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "16:9"}}

    shared = build_images(Settings(image_provider="gemini", llm_api_key="agent-key", image_api_key=""))
    assert shared.enabled and shared._api_key == "agent-key"
    assert not build_images(Settings(image_provider="openai", llm_api_key="agent-key", image_api_key="")).enabled


def test_gemini_drops_the_aspect_ratio_for_models_that_reject_it():
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "imageConfig" in body["generationConfig"]:
            return httpx.Response(400, json={"error": {"message": 'Invalid JSON payload received. Unknown name "imageConfig"'}})
        return httpx.Response(200, json=gemini_reply("image/jpeg"))

    images = ImageGen("gemini", api_key="k", model="gemini-2.5-flash-image",
                      http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert asyncio.run(images.generate("a cafe")) == "data:image/jpeg;base64,QUJD"
    assert len(bodies) == 2


def test_openai_image_sizes_follow_the_model():
    from app.images import openai_size

    assert openai_size("gpt-image-1", "16:9") == "1536x1024"
    assert openai_size("gpt-image-1", "9:16") == "1024x1536"
    assert openai_size("dall-e-3", "16:9") == "1024x1024"


def test_cloudflare_images_return_a_data_url():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer token"
        assert "flux-1-schnell" in str(request.url)
        return httpx.Response(200, json={"success": True, "result": {"image": "QUJD"}})

    images = ImageGen("cloudflare", "account", "token", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert images.enabled
    assert asyncio.run(images.generate("a cafe interior")) == "data:image/jpeg;base64,QUJD"
    assert not ImageGen("cloudflare", "", "").enabled
