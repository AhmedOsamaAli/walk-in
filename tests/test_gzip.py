"""Gzip from the backend: JSON goes out four times smaller to clients that accept it, and the same bytes once
decompressed; the survey stream is never compressed or held back, so each event leaves as soon as it is made."""
from __future__ import annotations

import asyncio
import gzip
from urllib.parse import urlencode

import pytest

from app.main import create_app
from tests.account_fakes import RUN_PARAMS, configure, make_client, run_survey, sse_events
from tests.test_e2e import GatedWalker, make_services


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    return configure(monkeypatch)


def raw_get(client, path: str, accept: str | None) -> tuple[int, dict, bytes]:
    """A GET as it goes over the wire: no decoding by the test client."""
    async def call() -> tuple[int, dict, bytes]:
        messages: list[dict] = []
        asked = False
        route, _, query = path.partition("?")
        headers = [(b"host", b"testserver")] + ([(b"accept-encoding", accept.encode())] if accept else [])
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
                 "path": route, "raw_path": route.encode(), "root_path": "", "query_string": query.encode(),
                 "headers": headers, "client": ("127.0.0.1", 50000), "server": ("testserver", 80)}

        async def receive() -> dict:
            nonlocal asked
            if not asked:
                asked = True
                return {"type": "http.request", "body": b"", "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message: dict) -> None:
            messages.append(message)

        await client.app(scope, receive, send)
        start = next(m for m in messages if m["type"] == "http.response.start")
        body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
        return start["status"], {k.decode(): v.decode() for k, v in start["headers"]}, body

    return client.portal.call(call)


def test_json_goes_out_gzipped_to_clients_that_accept_it_and_as_it_is_to_others():
    with make_client() as client:
        run_id = run_survey(client)
        catchment = "/api/catchment?" + urlencode({"lat": 40.0, "lon": -73.0, "minutes": 15})
        for path in (f"/api/runs/{run_id}", catchment):  # a cached page, and an ordinary route
            status, plain_headers, plain = raw_get(client, path, None)
            status_gz, headers, zipped = raw_get(client, path, "gzip, deflate, br")
            assert status == status_gz == 200 and "content-encoding" not in plain_headers
            assert headers["content-encoding"] == "gzip" and "accept-encoding" in headers["vary"].lower()
            assert gzip.decompress(zipped) == plain and len(zipped) * 2 < len(plain), path
            assert headers["cache-control"] == plain_headers["cache-control"]
        _, headers, small = raw_get(client, "/api/presets", "gzip")  # under 1 KB: not worth it
        assert "content-encoding" not in headers and small.startswith(b"[")


def test_the_survey_stream_is_never_compressed_and_each_event_leaves_at_once(database_url):
    walker = GatedWalker()
    services = make_services(walker=walker)
    app = create_app(lambda: services, database_url)

    async def stream() -> tuple[dict, list[bytes], list[bytes]]:
        bodies: list[bytes] = []
        before_the_walk: list[bytes] = []
        started: dict = {}
        ended = asyncio.Event()
        asked = False

        async def receive() -> dict:
            nonlocal asked
            if not asked:
                asked = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await ended.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict) -> None:
            if message["type"] == "http.response.start":
                started.update({k.decode(): v.decode() for k, v in message["headers"]})
            elif message["type"] == "http.response.body":
                if message.get("body"):
                    bodies.append(message["body"])
                    if not walker.gate.is_set():
                        before_the_walk.append(message["body"])
                        if len(before_the_walk) == 2:  # the survey is held at its walk: these left without waiting
                            walker.gate.set()
                if not message.get("more_body"):
                    ended.set()

        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
                 "path": "/api/run", "raw_path": b"/api/run", "root_path": "", "query_string": urlencode(RUN_PARAMS).encode(),
                 "headers": [(b"host", b"testserver"), (b"accept-encoding", b"gzip, deflate, br")],
                 "client": ("127.0.0.1", 50000), "server": ("testserver", 80)}
        async with app.router.lifespan_context(app):
            await asyncio.wait_for(app(scope, receive, send), 60)
        return started, bodies, before_the_walk

    started, bodies, before_the_walk = asyncio.run(stream())
    assert started["content-type"].startswith("text/event-stream") and "content-encoding" not in started
    assert [chunk.split(b"\n", 1)[0] for chunk in before_the_walk] == [b"event: run", b"event: status"]
    events = sse_events(b"".join(bodies).decode())
    assert len(bodies) == len(events) and events[-1][0] == "done"  # one write per event, none held back or merged
    assert all(chunk.endswith(b"\n\n") and chunk.count(b"\nevent: ") == 0 for chunk in bodies)
