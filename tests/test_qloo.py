"""The Qloo client's cache: a week-old answer is fresh; an older one is refreshed, and serves only when Qloo cannot
answer. Each survey counts the answers it read, apart from surveys running at the same time."""
import asyncio
import os
import time

import httpx
import pytest

from app import jsonio
from app.qloo import MAX_AGE_S, QlooClient, QlooError, track_reads

PARAMS = {"filter.type": "urn:entity:place", "take": 1}


def client(tmp_path, answers: list[dict] | None = None, status: int = 200, key: str = "k") -> tuple[QlooClient, list]:
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(status, json=answers.pop(0) if answers else {})

    q = QlooClient(key, "https://qloo.test", tmp_path)
    q._http = httpx.AsyncClient(base_url="https://qloo.test", transport=httpx.MockTransport(handle))
    return q, seen


def age(q: QlooClient, seconds: float) -> None:
    """Makes the cached answer to PARAMS this many seconds old."""
    path = q._cache_dir / f"{q._cache_key('/v2/insights', PARAMS)}.json"
    then = time.time() - seconds
    os.utime(path, (then, then))


def test_a_fresh_answer_is_served_from_the_cache(tmp_path):
    q, seen = client(tmp_path, [{"v": 1}, {"v": 2}])
    assert asyncio.run(q.insights(PARAMS)) == {"v": 1}
    age(q, MAX_AGE_S - 3600)
    assert asyncio.run(q.insights(PARAMS)) == {"v": 1}
    assert len(seen) == 1 and q.cache_hits == 1


def test_an_answer_older_than_a_week_is_asked_again(tmp_path):
    q, seen = client(tmp_path, [{"v": 1}, {"v": 2}])
    asyncio.run(q.insights(PARAMS))
    age(q, MAX_AGE_S + 3600)
    assert asyncio.run(q.insights(PARAMS)) == {"v": 2}
    assert len(seen) == 2


@pytest.mark.parametrize("status", [401, 403])
def test_an_old_answer_serves_when_qloo_refuses_the_key(tmp_path, status):
    q, _ = client(tmp_path, [{"v": 1}])
    asyncio.run(q.insights(PARAMS))
    age(q, 30 * 24 * 3600)
    q, seen = client(tmp_path, status=status)

    async def survey():
        reads = track_reads()
        return await q.insights(PARAMS), reads

    data, reads = asyncio.run(survey())
    assert data == {"v": 1} and len(seen) == 1
    assert reads.queries == 1 and time.time() - reads.oldest > 29 * 24 * 3600


def test_without_a_key_or_a_saved_answer_the_query_fails(tmp_path):
    q, _ = client(tmp_path, key="")
    with pytest.raises(QlooError):
        asyncio.run(q.insights(PARAMS))


def test_surveys_running_at_once_count_their_own_reads(tmp_path):
    q, _ = client(tmp_path, [{"v": i} for i in range(10)])

    async def survey(n: int):
        reads = track_reads()
        for i in range(n):
            await q.insights({**PARAMS, "page": f"{n}-{i}"})
        return reads

    async def both():
        return await asyncio.gather(asyncio.create_task(survey(2)), asyncio.create_task(survey(3)))

    first, second = asyncio.run(both())
    assert (first.queries, second.queries) == (2, 3)


def test_an_answer_is_kept_as_qloo_sent_it(tmp_path):
    sent = b'{"results": {"entities": [{"name": "Caf\xc3\xa9", "popularity": 0.90}]}, "duration": 12}'

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sent, headers={"content-type": "application/json"})

    q = QlooClient("k", "https://qloo.test", tmp_path)
    q._http = httpx.AsyncClient(base_url="https://qloo.test", transport=httpx.MockTransport(handle))
    assert asyncio.run(q.insights(PARAMS)) == {"results": {"entities": [{"name": "Café", "popularity": 0.9}]}, "duration": 12}
    assert (tmp_path / f"{q._cache_key('/v2/insights', PARAMS)}.json").read_bytes() == sent  # not parsed and written again
    assert asyncio.run(q.insights(PARAMS))["results"]["entities"][0]["name"] == "Café" and q.cache_hits == 1


def test_the_cache_is_read_off_the_event_loop(tmp_path, monkeypatch):
    q, _ = client(tmp_path, [{"v": 1}])
    asyncio.run(q.insights(PARAMS))
    real_read = jsonio.read

    def slow_disk(path):
        time.sleep(0.3)  # a slow disk: the loop must keep serving meanwhile
        return real_read(path)

    monkeypatch.setattr(jsonio, "read", slow_disk)

    async def read_while_ticking() -> tuple[dict, int]:
        ticks = 0

        async def tick() -> None:
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        ticker = asyncio.create_task(tick())
        data = await q.insights(PARAMS)
        ticker.cancel()
        return data, ticks

    data, ticks = asyncio.run(read_while_ticking())
    assert data == {"v": 1} and ticks >= 10
