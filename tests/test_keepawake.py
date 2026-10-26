"""Keeping a free Render instance awake: the app visits its own health check every few minutes while it runs."""
from __future__ import annotations

import asyncio
from dataclasses import replace

import httpx
import pytest

from app import config, main
from app.keepawake import keep_awake
from tests.account_fakes import make_client

URL = "https://walk-in.example/api/health"


def visits(*answers: int | Exception) -> list[httpx.Request]:
    """Runs the loop, a visit every 10 ms, until it has had each answer in turn; returns the requests it made."""
    seen: list[httpx.Request] = []

    async def scenario() -> None:
        done = asyncio.Event()

        def reply(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            answer = answers[min(len(seen), len(answers)) - 1]
            if len(seen) >= len(answers):
                done.set()
            if isinstance(answer, Exception):
                raise answer
            return httpx.Response(answer)

        task = asyncio.create_task(keep_awake(URL, every=0.01, transport=httpx.MockTransport(reply)))
        await asyncio.wait_for(done.wait(), 5)
        task.cancel()
        await asyncio.wait([task])
        assert task.cancelled()  # stopped by the cancel, not by an error

    asyncio.run(scenario())
    return seen


def test_it_visits_the_health_check_again_and_again():
    seen = visits(200, 200, 200)
    assert [(request.method, str(request.url)) for request in seen] == [("GET", URL)] * 3
    assert seen[0].headers["user-agent"] == "Walk-in keep-awake"


def test_a_failed_visit_does_not_stop_the_next():
    assert len(visits(httpx.ConnectError("unreachable"), 503, 200)) == 3


def test_it_is_on_where_render_gives_the_service_a_public_address(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("KEEP_AWAKE", raising=False)
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    assert config.Settings().keep_awake_url == ""  # development and tests
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://walk-in-aoa2.onrender.com/")
    assert config.Settings().keep_awake_url == "https://walk-in-aoa2.onrender.com/api/health"
    monkeypatch.setenv("KEEP_AWAKE", "0")
    assert config.Settings().keep_awake_url == ""


@pytest.mark.parametrize("url", [URL, ""])
def test_the_app_runs_it_while_it_runs(monkeypatch: pytest.MonkeyPatch, url: str):
    calls: list[str] = []

    async def fake_keep_awake(target: str) -> None:
        calls.append(f"start {target}")
        try:
            await asyncio.Event().wait()
        finally:
            calls.append("stop")

    monkeypatch.setattr(main, "keep_awake", fake_keep_awake)
    monkeypatch.setattr(main, "settings", replace(main.settings, keep_awake_url=url))
    with make_client() as client:
        assert client.get("/api/health").status_code == 200
    assert calls == ([f"start {URL}", "stop"] if url else [])
