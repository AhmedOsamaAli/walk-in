import asyncio
import json
import time

import httpx
import pytest

from app.images import ImageGen
from app.llm import (
    CUT_NOTE,
    LLM,
    SIGNATURE_SENTINEL,
    LLMUnavailable,
    Provider,
    approx_tokens,
    fit,
    neutralize_signatures,
    parse_json,
)


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


def groq_limit(message: str, status: int = 429, retry_after: str = "22") -> httpx.Response:
    return httpx.Response(status, headers={"retry-after": retry_after}, json={"error": {
        "message": message, "type": "tokens", "code": "rate_limit_exceeded"}})


def two_providers(replies: dict[str, list[httpx.Response]], seen: list[tuple[str, dict]], **kwargs) -> LLM:
    """Gemini as the main provider and Groq after it, each answering from its own queue."""
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.host, json.loads(request.content), request.headers["authorization"]))
        return replies[request.url.host].pop(0)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    groq = Provider("groq-key", "https://groq.test/v1", ("groq-big", "groq-small"), reasoning_effort="low",
                    token_limit=kwargs.pop("token_limit", 8000))
    return LLM("gemini-key", "https://gemini.test/v1/", "gemini-3.6-flash", http_client=client, also=[groq], **kwargs)


def test_a_second_provider_answers_when_the_first_is_out_of_quota():
    seen: list = []
    llm = two_providers({
        "gemini.test": [rate_limited("Day", "20s")],
        "groq.test": [httpx.Response(200, json=completion({"role": "assistant", "content": '{"ok": 1}'}, "groq-big"))],
    }, seen)
    assert llm.models == ["gemini-3.6-flash", "groq-big", "groq-small"] and llm.model == "gemini-3.6-flash"
    assert asyncio.run(llm.complete_json("system", "user")) == ({"ok": 1}, "groq-big")
    (gemini_host, gemini, gemini_key), (groq_host, groq, groq_key) = seen
    assert (gemini_host, gemini_key, "reasoning_effort" in gemini) == ("gemini.test", "Bearer gemini-key", False)
    assert (groq_host, groq_key, groq["model"], groq["reasoning_effort"]) == ("groq.test", "Bearer groq-key", "groq-big", "low")
    assert llm.resting()["gemini-3.6-flash"] > 3500


def test_only_groq_configured_still_enables_the_agent():
    from app.config import Settings
    from app.providers import build_llm

    llm = build_llm(Settings(llm_api_key="", groq_api_key="groq-key", groq_models=("openai/gpt-oss-120b",)))
    assert llm.enabled and llm.models == ["openai/gpt-oss-120b"] and llm.model == "openai/gpt-oss-120b"
    assert not build_llm(Settings(llm_api_key="", groq_api_key="")).enabled


def test_a_turn_from_another_provider_is_sent_with_standard_fields_only():
    seen: list = []
    llm = two_providers({
        "gemini.test": [
            httpx.Response(200, json=completion({
                "role": "assistant", "content": None, "extra_content": {"google": {"thought_signature": "msg-sig"}},
                "tool_calls": [tool_call("c1", "inspect_gap", {"genre": "Bakery"}, signature="call-sig")],
            }, "gemini-3.6-flash")),
            httpx.Response(503, json={"error": {"message": "overloaded"}}),
        ],
        "groq.test": [httpx.Response(200, json=completion({
            "role": "assistant", "content": None, "reasoning": "Done checking.",
            "tool_calls": [tool_call("c2", "submit_concepts", {"concepts": []})],
        }, "groq-big"))],
    }, seen)

    async def inspect(args):
        return {"genre": args["genre"]}

    result, model = asyncio.run(llm.run_tools("s", "u", [], {"inspect_gap": inspect}, final_tool="submit_concepts"))
    assert (result, model) == ({"concepts": []}, "groq-big")
    on_gemini, on_groq = seen[1][1]["messages"][2], seen[2][1]["messages"][2]
    assert on_gemini["extra_content"] == {"google": {"thought_signature": "msg-sig"}}  # its own turn, as written
    assert set(on_groq) == {"role", "content", "tool_calls"}
    assert set(on_groq["tool_calls"][0]) == {"id", "type", "function"}
    assert all('"_model"' not in json.dumps(body) for _, body, _ in seen)


def test_groq_rate_limits_rest_for_the_advised_time():
    seen: list = []
    llm = two_providers({
        "gemini.test": [rate_limited("Day")],
        "groq.test": [
            groq_limit("Rate limit reached for model `groq-big` on tokens per minute (TPM): Limit 8000, Used 5321, "
                       "Requested 5598. Please try again in 21.8925s."),
            groq_limit("Rate limit reached for model `groq-small` on requests per day (RPD): Limit 1000, Used 1000, "
                       "Requested 1. Please try again in 1m26.4s.", retry_after="87"),
        ],
    }, seen)
    with pytest.raises(LLMUnavailable) as error:
        asyncio.run(llm.complete_json("system", "user"))
    resting = llm.resting()
    assert 22 <= resting["groq-big"] <= 23 and 87 <= resting["groq-small"] <= 88
    assert "HTTP 429 (rate limit)" in str(error.value) and "groq-small: HTTP 429 (daily quota)" in str(error.value)


def test_a_request_too_large_for_one_model_moves_on_without_resting_it():
    seen: list = []
    llm = two_providers({
        "gemini.test": [rate_limited("Day")],
        "groq.test": [
            groq_limit("Request too large for model `groq-big` on tokens per minute (TPM): Limit 8000, Requested 11577, "
                       "please reduce your message size and try again.", status=413, retry_after="27"),
            httpx.Response(200, json=completion({"role": "assistant", "content": '{"ok": 2}'}, "groq-small")),
        ],
    }, seen)
    assert asyncio.run(llm.complete_json("system", "user")) == ({"ok": 2}, "groq-small")
    assert "groq-big" not in llm.resting()


def test_the_agent_waits_for_a_model_that_comes_back_soon():
    seen: list = []
    llm = two_providers({
        "gemini.test": [rate_limited("Day")],
        "groq.test": [
            groq_limit("Rate limit reached on tokens per minute (TPM). Please try again in 50ms."),
            groq_limit("Rate limit reached on tokens per minute (TPM). Please try again in 80ms."),
            httpx.Response(200, json=completion({"role": "assistant", "content": '{"ok": 3}'}, "groq-big")),
        ],
    }, seen, max_wait=5)
    waits: list = []

    async def on_wait(seconds: float, phase: str) -> None:
        waits.append((phase, seconds))

    started = time.perf_counter()
    response, model = asyncio.run(llm._create([{"role": "user", "content": "u"}], on_wait=on_wait))
    assert model == "groq-big" and [phase for phase, _ in waits] == ["start", "end"]
    assert 0.9 < waits[0][1] < 1.2 and time.perf_counter() - started < 3
    impatient = two_providers({"gemini.test": [rate_limited("Day")], "groq.test": [
        groq_limit("Please try again in 50ms."), groq_limit("Please try again in 50ms.")]}, [], max_wait=0.5)
    with pytest.raises(LLMUnavailable):
        asyncio.run(impatient.complete_json("system", "user"))


def test_long_tool_results_are_cut_oldest_first_to_fit_a_token_limit():
    turn = {"role": "assistant", "content": None, "reasoning": "x" * 800, "tool_calls": [tool_call("c1", "t", {})]}
    messages = [
        {"role": "system", "content": "s"}, {"role": "user", "content": "u"},
        turn, {"role": "tool", "tool_call_id": "c1", "content": "a" * 6000},
        turn, {"role": "tool", "tool_call_id": "c1", "content": "b" * 6000},
    ]
    fitted = fit(messages, None, 2000)
    assert fitted is not None and approx_tokens(fitted, None) <= 1800
    oldest, newest = fitted[3]["content"], fitted[5]["content"]
    assert oldest.endswith(CUT_NOTE) and len(oldest) <= len(newest)
    assert "reasoning" not in fitted[2] and messages[3]["content"] == "a" * 6000  # the history is untouched
    assert fit(messages, None, 100_000) is messages
    assert fit([{"role": "user", "content": "u" * 20_000}], None, 2000) is None


def test_a_token_limited_provider_gets_a_conversation_that_fits():
    seen: list = []
    llm = two_providers({
        "gemini.test": [rate_limited("Day")],
        "groq.test": [
            httpx.Response(200, json=completion({"role": "assistant", "content": None,
                                                 "tool_calls": [tool_call("c1", "inspect_gap", {"genre": "Bakery"})]}, "groq-big")),
            httpx.Response(200, json=completion({"role": "assistant", "content": None,
                                                 "tool_calls": [tool_call("c2", "submit", {"done": True})]}, "groq-big")),
        ],
    }, seen, token_limit=1500)

    async def inspect(args):
        return {"places": ["Bakery near the site"] * 400}

    result, _ = asyncio.run(llm.run_tools("s", "u", [], {"inspect_gap": inspect}, final_tool="submit"))
    assert result == {"done": True}
    second = seen[-1][1]["messages"]
    assert second[-1]["role"] == "tool" and second[-1]["content"].endswith(CUT_NOTE)
    assert approx_tokens(second, None) <= 1350


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
    assert shared.enabled and shared.providers[0]._api_key == "agent-key"
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


def horde_transport(seen: list, states: list[dict], generations: list[dict] | None = None) -> httpx.MockTransport:
    """A fake AI Horde: accepts a job, reports the given check states in turn, then serves the result."""
    checks = states  # shared, so a test can change what the Horde reports between calls

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, dict(request.headers), request.content))
        path = request.url.path
        if request.method == "POST" and path.endswith("/generate/async"):
            return httpx.Response(202, json={"id": "job-1", "kudos": 6})
        if path.endswith("/generate/check/job-1"):
            return httpx.Response(200, json=checks.pop(0) if len(checks) > 1 else checks[0])
        if request.method == "DELETE":
            return httpx.Response(200, json={"cancelled": True})
        if path.endswith("/generate/status/job-1"):
            return httpx.Response(200, json={"generations": generations or [{"img": "https://r2.test/image.webp"}]})
        if request.url.host == "r2.test":
            return httpx.Response(200, content=b"RIFF....WEBP", headers={"content-type": "image/webp"})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_ai_horde_renders_without_a_key():
    seen: list = []
    transport = horde_transport(seen, [{"done": False, "queue_position": 3}, {"done": True}])
    images = ImageGen("horde", http_client=httpx.AsyncClient(transport=transport), poll_s=0)
    assert images.enabled and images.model == "Flux.1-Schnell fp8 (Compact) on AI Horde"
    image = asyncio.run(images.generate("a live music lounge", "16:9"))
    assert image.startswith("data:image/webp;base64,")
    method, path, headers, content = seen[0]
    body = json.loads(content)
    assert (method, path) == ("POST", "/api/v2/generate/async")
    assert headers["apikey"] == "0000000000" and headers["client-agent"].startswith("blank-space:")
    assert body["models"] == ["Flux.1-Schnell fp8 (Compact)"] and body["censor_nsfw"] is True
    assert (body["params"]["width"], body["params"]["height"]) == (1024, 576)


def test_ai_horde_keeps_its_place_in_a_long_queue_and_resumes_it():
    seen: list = []
    states = [{"done": False, "queue_position": 300}]
    transport = horde_transport(seen, states)
    images = ImageGen("horde", http_client=httpx.AsyncClient(transport=transport), poll_s=0, wait_s=0)
    with pytest.raises(TimeoutError):
        asyncio.run(images.generate("a cafe"))
    states[0] = {"done": True}
    assert asyncio.run(images.generate("a cafe")).startswith("data:image/webp")
    requests = [(m, p) for m, p, _, _ in seen]
    assert requests.count(("POST", "/api/v2/generate/async")) == 1  # the retry resumed the queued job
    assert ("DELETE", "/api/v2/generate/status/job-1") not in requests


def test_ai_horde_leaves_the_queue_when_the_server_stops_waiting():
    seen: list = []
    images = ImageGen("horde", http_client=httpx.AsyncClient(transport=horde_transport(seen, [{"done": False}])),
                      poll_s=0.01, wait_s=60)

    async def stop_early():
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(images.generate("a cafe"), 0.2)

    asyncio.run(stop_early())
    assert ("DELETE", "/api/v2/generate/status/job-1") in [(m, p) for m, p, _, _ in seen]


def test_ai_horde_censored_results_count_as_no_image():
    transport = horde_transport([], [{"done": True}], generations=[{"img": "https://r2.test/x.webp", "censored": True}])
    images = ImageGen("horde", http_client=httpx.AsyncClient(transport=transport), poll_s=0)
    assert asyncio.run(images.generate("a cafe")) is None


def test_the_chain_falls_back_to_the_next_provider():
    from app.images import ImageChain

    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"errors": [{"code": 4006, "message": "daily free allocation used"}]})

    cloudflare = ImageGen("cloudflare", "account", "token", http_client=httpx.AsyncClient(transport=httpx.MockTransport(broken)))
    horde = ImageGen("horde", http_client=httpx.AsyncClient(transport=horde_transport([], [{"done": True}])), poll_s=0)
    chain = ImageChain([ImageGen("gemini"), cloudflare, horde])  # gemini has no key, so it is skipped
    assert chain.enabled and chain.provider == "cloudflare,horde" and chain.model == "flux-2-klein-4b"
    image, model = asyncio.run(chain.render("a cafe"))
    assert image.startswith("data:image/webp") and model.endswith("on AI Horde")

    only_broken = ImageChain([ImageGen("cloudflare", "a", "t", http_client=httpx.AsyncClient(transport=httpx.MockTransport(broken)))])
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(only_broken.render("a cafe"))
    assert asyncio.run(ImageChain([ImageGen("gemini")]).render("a cafe")) == (None, None)


def test_cloudflare_flux2_sends_the_size_as_a_form():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers["content-type"], request.content))
        return httpx.Response(200, json={"success": True, "result": {"image": "iVBORw0KGgoAAAANSUhEUg"}})

    images = ImageGen("cloudflare", "account", "token", model="@cf/black-forest-labs/flux-2-klein-4b",
                      http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert images.model == "flux-2-klein-4b"
    assert asyncio.run(images.generate("a cafe", "16:9")) == "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg"
    url, content_type, content = seen[0]
    assert url.endswith("/accounts/account/ai/run/@cf/black-forest-labs/flux-2-klein-4b")
    assert content_type.startswith("multipart/form-data")
    assert b'name="width"\r\n\r\n1280' in content and b'name="height"\r\n\r\n720' in content


def test_image_providers_are_chained_from_settings():
    from app.config import Settings
    from app.images import sized
    from app.providers import build_images

    chain = build_images(Settings(image_provider="cloudflare, horde,cloudflare", cloudflare_account_id="", cloudflare_api_token=""))
    assert [p.provider for p in chain.providers] == ["cloudflare", "horde"]
    assert chain.enabled and chain.provider == "horde"  # Cloudflare waits for its keys
    assert sized("16:9", 1024, 64) == (1024, 576) and sized("9:16", 1280, 16) == (720, 1280)
    assert sized("bad", 1024, 64) == (1024, 1024)


def test_cloudflare_images_return_a_data_url():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer token"
        assert "flux-1-schnell" in str(request.url)
        return httpx.Response(200, json={"success": True, "result": {"image": "QUJD"}})

    images = ImageGen("cloudflare", "account", "token", model="@cf/black-forest-labs/flux-1-schnell",
                      http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert images.enabled
    assert asyncio.run(images.generate("a cafe interior")) == "data:image/jpeg;base64,QUJD"
    assert not ImageGen("cloudflare", "", "").enabled
