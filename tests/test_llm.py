import asyncio
import json
import time

import httpx
import pytest

from app.llm import (
    CUT_NOTE,
    LLM,
    SIGNATURE_SENTINEL,
    LLMUnavailable,
    Provider,
    approx_tokens,
    compact_json,
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
    assert second[3] == {"role": "tool", "tool_call_id": "c1", "content": '{"ok":true}'}  # compact JSON
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
    assert results == ['{"n":1}', '{"n":2}', '{"error":"broken failed (ValueError)"}']  # compact JSON


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


def resting_a_second() -> httpx.Response:
    return groq_limit("Rate limit reached on tokens per minute (TPM). Please try again in 50ms.")


def agent_on_resting_models(**kwargs) -> tuple[LLM, list, list]:
    """Every model rests about a second before each of the agent's turns; the first turn asks for a check."""
    seen, waits = [], []
    check = completion({"role": "assistant", "content": None, "tool_calls": [tool_call("c1", "inspect_gap", {})]}, "groq-big")
    done = completion({"role": "assistant", "content": None, "tool_calls": [tool_call("c2", "submit_concepts", {})]},
                      "groq-big")
    llm = two_providers({"gemini.test": [rate_limited("Day")], "groq.test": [
        resting_a_second(), resting_a_second(), httpx.Response(200, json=check),
        resting_a_second(), resting_a_second(), httpx.Response(200, json=done),
    ]}, seen, max_wait=5, **kwargs)
    return llm, seen, waits


def run_agent(llm: LLM, waits: list) -> tuple[dict | None, str | None]:
    async def inspect(args):
        return {"ok": True}

    async def on_wait(seconds: float, phase: str) -> None:
        waits.append((phase, round(seconds, 1)))

    return asyncio.run(llm.run_tools("s", "u", [], {"inspect_gap": inspect}, final_tool="submit_concepts",
                                     on_wait=on_wait))


def test_one_conversation_waits_for_resting_models_within_its_budget_only():
    """AGENT_WAIT_BUDGET: a survey's agent waits this long at most, in all, for resting models; a wait that would go past
    it is not started, and the agent stops as when every model is resting past LLM_MAX_WAIT."""
    llm, seen, waits = agent_on_resting_models()  # no budget: it waits before each turn and finishes
    assert run_agent(llm, waits) == ({}, "groq-big") and [phase for phase, _ in waits] == ["start", "end"] * 2

    llm, seen, waits = agent_on_resting_models(wait_budget=1.5)  # room for one wait of a second, not two
    started = time.perf_counter()
    with pytest.raises(LLMUnavailable) as error:
        run_agent(llm, waits)
    assert [phase for phase, _ in waits] == ["start", "end"] and time.perf_counter() - started < 1.9
    assert "wait budget" in str(error.value) and len(seen) == 6  # the second turn found both models resting, and stopped

    llm, seen, waits = agent_on_resting_models(wait_budget=0.5)  # not even one wait fits
    started = time.perf_counter()
    with pytest.raises(LLMUnavailable):
        run_agent(llm, waits)
    assert waits == [] and time.perf_counter() - started < 0.5


def test_tool_results_and_prompts_are_compact_json():
    value = {"genre": "Café", "rank": 8.0, "share": 0.35, "missing": None, "rows": [1.0, None, {"x": None, "y": 2.5}],
             "flag": True, "nested": {"km": 3.0, "text": "a, b: c"}}
    assert compact_json(value) == ('{"genre":"Café","rank":8,"share":0.35,"rows":[1,null,{"y":2.5}],"flag":true,'
                                   '"nested":{"km":3,"text":"a, b: c"}}')
    assert json.loads(compact_json(value))["rows"][1] is None  # a list keeps its places


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
