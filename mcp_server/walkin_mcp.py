"""Walk-in as a tool for AI assistants: a stdio MCP server over Walk-in's public HTTP API.

Walk-in surveys an empty storefront. It traces the real walk or drive area around it, reads Qloo's taste data for the
people there, ranks what the area is missing, designs concepts checked against that evidence and builds a free launch
kit. With this server, Claude Desktop, VS Code Copilot or any other MCP client can use it as a tool:

- survey_storefront runs a survey: GET /api/geocode for a place, then GET /api/run, read as server-sent events;
- list_examples lists the finished surveys anyone can open: GET /api/examples;
- get_survey reads a survey again: GET /api/runs/{run_id}.

It talks to nothing but WALKIN_URL (default https://walkin-app.pages.dev, whose front door forwards /api to the survey
engine) and needs no keys. Run it with `python mcp_server/walkin_mcp.py`: it speaks MCP over stdin and stdout.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable, Iterator
from typing import Annotated, Any, Literal

import anyio
import httpx
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

DEFAULT_URL = "https://walkin-app.pages.dev"
SURVEY_WAIT_S = 240.0  # a survey takes one to three minutes, and the free server up to one more to wake
CALL_WAIT_S = 150.0  # any other call, waking included
TOP_GAPS = 5
RUN_ID = re.compile(r"[A-Za-z0-9-]{1,32}")
SURVEY_LINK = re.compile(r"/s/([A-Za-z0-9-]{1,32})(?:[/?#]|$)")
USER_AGENT = "walkin-mcp/1.0"

TOO_MANY_SURVEYS = "Walk-in allows a few surveys per hour from one address; try again later."
CREDIT = "Data: Qloo taste data · OpenStreetMap (© OpenStreetMap contributors) · Valhalla routing."
SHAPES = {"street network": "traced over the street network",
          "circle": "drawn as a circle because street routing was unavailable"}

Travel = Literal["walk", "drive", "distance"]
Ages = Literal["all", "under_25", "25_34", "35_54", "55_plus"]
Notify = Callable[[str | None], Awaitable[None]]


class WalkinError(Exception):
    """What went wrong, in plain words for the assistant to pass on."""


# ---------- Server-sent events ----------

async def read_events(
    lines: AsyncIterable[str], heartbeat: Callable[[], Awaitable[Any]] | None = None,
) -> AsyncIterator[tuple[str, Any]]:
    """Server-sent events as (name, data), the data decoded from JSON.

    Follows the event-stream format: a line starting with ':' is a comment (Walk-in sends ': keep-alive' after 15
    quiet seconds, which calls `heartbeat`), a blank line ends an event, an event without a name is a 'message', and
    one the stream ends in the middle of is dropped.
    """
    name, data = "", []
    async for raw in lines:
        line = raw.rstrip("\r\n")
        if not line:
            if data:
                yield name or "message", decoded("\n".join(data))
            name, data = "", []
        elif line.startswith(":"):
            if heartbeat is not None:
                await heartbeat()
        else:
            field, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if field == "event":
                name = value
            elif field == "data":
                data.append(value)


def decoded(data: str) -> Any:
    try:
        return json.loads(data)
    except ValueError:
        return data


# ---------- Walk-in's API ----------

class Progress:
    """Survey steps, told to the client as MCP progress notifications when it asked for them (a progressToken).

    They show the user what the survey is doing, and clients that restart their timeout on progress keep waiting for
    a survey that takes minutes: every event and keep-alive is one, so one comes at least every 15 seconds. A call
    without a message repeats the step under way. Progress is a courtesy: a client that did not ask, or went away, is
    not told.
    """

    def __init__(self, ctx: Context | None = None) -> None:
        self.ctx = ctx
        self.count = 0
        self.message: str | None = None

    async def __call__(self, message: str | None = None) -> None:
        self.count += 1
        self.message = message or self.message
        if self.ctx is not None:
            with contextlib.suppress(Exception):
                await self.ctx.report_progress(self.count, None, self.message)


async def quiet(message: str | None = None) -> None:
    return None


def wait_from_env() -> float:
    """How long survey_storefront waits for a survey to end: WALKIN_WAIT_SECONDS (10 to 600), else 4 minutes."""
    try:
        seconds = float(os.environ.get("WALKIN_WAIT_SECONDS", ""))
    except ValueError:
        return SURVEY_WAIT_S
    return min(600.0, max(10.0, seconds))


class Walkin:
    """Walk-in's public API as the tools use it: GETs that wait through the free server's naps, and the survey stream
    read to its end."""

    def __init__(
        self, base: str | None = None, *, transport: httpx.AsyncBaseTransport | None = None,
        survey_wait: float | None = None, sleep: Callable[[float], Awaitable[Any]] = anyio.sleep,
    ) -> None:
        self.base = (base or os.environ.get("WALKIN_URL") or DEFAULT_URL).strip().rstrip("/")
        self.transport = transport
        self.survey_wait = wait_from_env() if survey_wait is None else survey_wait
        self.sleep = sleep

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base, transport=self.transport, follow_redirects=True,
            timeout=httpx.Timeout(60.0, connect=20.0), headers={"User-Agent": USER_AGENT},
        )

    def link(self, path: str) -> str:
        """An absolute link to one of Walk-in's pages, from the path the API gives ('/s/{run_id}', '/k/{token}')."""
        return path if path.startswith(("http://", "https://")) else f"{self.base}/{path.lstrip('/')}"

    def unreachable(self, exc: httpx.HTTPError) -> str:
        reason = str(exc).strip() or type(exc).__name__
        return f"Could not reach Walk-in at {self.base} ({reason}). Check the connection, or WALKIN_URL."

    async def get(
        self, http: httpx.AsyncClient, path: str, params: dict[str, Any] | None = None, *,
        accept: str = "application/json", progress: Notify = quiet,
    ) -> httpx.Response:
        """GET path as an open response, which the caller reads and closes.

        While the free server wakes (about a minute after a quiet spell), the front door answers 503 {"waking": true}:
        that is asked again after its Retry-After. Any other failure raises WalkinError in plain words.
        """
        while True:
            request = http.build_request("GET", path, params=params, headers={"Accept": accept})
            try:
                response = await http.send(request, stream=True)
            except httpx.HTTPError as exc:
                raise WalkinError(self.unreachable(exc)) from exc
            if not response.is_error:
                return response
            try:
                await response.aread()
            except httpx.HTTPError as exc:
                raise WalkinError(self.unreachable(exc)) from exc
            finally:
                await close(response)
            if not waking(response):
                raise WalkinError(failure(response, path))
            await progress("Walk-in's free server is waking up; that takes about a minute.")
            await self.sleep(retry_after(response))

    async def get_json(self, http: httpx.AsyncClient, path: str, params: dict[str, Any] | None = None, *,
                       progress: Notify = quiet) -> Any:
        response = await self.get(http, path, params, progress=progress)
        try:
            await response.aread()
        except httpx.HTTPError as exc:
            raise WalkinError(self.unreachable(exc)) from exc
        finally:
            await close(response)
        body = json_of(response)
        if body is None:
            raise WalkinError(f"Walk-in at {self.base} sent a page instead of data; check WALKIN_URL.")
        return body

    async def survey(
        self, *, place: str | None = None, lat: float | None = None, lon: float | None = None, travel: Travel = "walk",
        minutes: int = 10, km: float | None = None, ages: Ages = "all", business: str | None = None,
        progress: Notify = quiet,
    ) -> str:
        """Runs a survey and summarizes it. A survey still running when the wait ends, or whose stream broke, is
        summarized as far as it got, with its link: it goes on at Walk-in without anyone listening."""
        place, business = (place or "").strip(), (business or "").strip()
        if place and not 3 <= len(place) <= 160:
            raise WalkinError("Give the place as an address or a neighborhood name of 3 to 160 characters.")
        if not place and (lat is None or lon is None):
            raise WalkinError("Say where the storefront is: a place or address to search for, or its lat and lon.")
        events: list[tuple[str, Any]] = []
        stopped = None  # why the summary ends before the survey did
        async with self.client() as http:
            try:
                with anyio.fail_after(self.survey_wait):
                    if place:
                        lat, lon, label = await self.locate(http, place, progress)
                    else:
                        label = f"Site at {lat:.4f}, {lon:.4f}"
                    params = run_params(lat, lon, label, travel, minutes, km, ages, business)
                    response = await self.get(http, "/api/run", params, accept="text/event-stream", progress=progress)
                    try:
                        if not response.headers.get("content-type", "").startswith("text/event-stream"):
                            raise WalkinError(f"Walk-in at {self.base} did not send a survey stream; check WALKIN_URL.")
                        async with contextlib.aclosing(read_events(response.aiter_lines(), progress)) as stream:
                            async for name, data in stream:
                                events.append((name, data))
                                await progress(self.step(name, data))
                                if name in ("done", "error"):
                                    break
                            else:
                                stopped = "Walk-in's stream ended early"
                    finally:
                        await close(response)
            except TimeoutError as exc:
                if not run_id_of(events):
                    raise WalkinError(
                        f"Walk-in did not start the survey within {duration(self.survey_wait)}; its free server may "
                        "still be waking up. Try again in a minute."
                    ) from exc
                stopped = f"this tool stopped waiting after {duration(self.survey_wait)}"
            except httpx.HTTPError as exc:
                if not run_id_of(events):
                    raise WalkinError(self.unreachable(exc)) from exc
                stopped = "the connection to Walk-in dropped"
        if stopped and not run_id_of(events):
            raise WalkinError("Walk-in ended the survey stream before the survey started; try again in a minute.")
        return summarize(events, self.base, stopped=stopped)

    async def locate(self, http: httpx.AsyncClient, place: str, progress: Notify) -> tuple[float, float, str]:
        """The place's first match in Walk-in's address search, and the site's name as the web app shortens it."""
        hits = await self.get_json(http, "/api/geocode", {"q": place}, progress=progress)
        hit = hits[0] if isinstance(hits, list) and hits and isinstance(hits[0], dict) else None
        if hit is None:
            raise WalkinError(f'Walk-in\'s address search found nothing for "{place}". Try a fuller address, or give lat and lon.')
        try:
            lat, lon = float(hit["lat"]), float(hit["lon"])
        except (KeyError, TypeError, ValueError) as exc:
            raise WalkinError("Walk-in's address search sent a place without coordinates.") from exc
        await progress(f"Found {text(hit.get('label')) or place} ({lat:.4f}, {lon:.4f})")
        return lat, lon, (short_label(hit.get("label")) or place)[:160]

    def step(self, name: str, data: Any) -> str | None:
        """What a survey event says while it runs: its link once it starts, then each step as Walk-in's page shows it."""
        if not isinstance(data, dict):
            return None
        run_id = text(data.get("run_id"))
        if name == "run" and run_id:
            return f"Survey started: {self.link(f'/s/{run_id}')}"
        if name == "status" and data.get("state") == "running":
            return text(data.get("label"))
        if name == "error":
            return text(data.get("message"))
        return None

    async def examples(self) -> str:
        async with self.client() as http:
            with answer_within(CALL_WAIT_S):
                found = await self.get_json(http, "/api/examples")
        return examples_summary(found, self)

    async def record(self, run_id: str) -> str:
        run_id = survey_id(run_id)
        async with self.client() as http:
            with answer_within(CALL_WAIT_S):
                record = await self.get_json(http, f"/api/runs/{run_id}")
        if not isinstance(record, dict):
            raise WalkinError("Walk-in sent a survey this tool cannot read.")
        events = [
            (event[0], event[1]) for event in record.get("events") or []
            if isinstance(event, list) and len(event) >= 2 and isinstance(event[0], str)
        ]
        return summarize(events, self.base, run_id=text(record.get("id")) or run_id, status=text(record.get("status")))


async def close(response: httpx.Response) -> None:
    """Closes a response even while the call is being cancelled, so its connection is not left open."""
    with anyio.CancelScope(shield=True):
        await response.aclose()


@contextlib.contextmanager
def answer_within(seconds: float) -> Iterator[None]:
    try:
        with anyio.fail_after(seconds):
            yield
    except TimeoutError as exc:
        raise WalkinError(
            f"Walk-in did not answer within {duration(seconds)}; its free server may still be waking up. "
            "Try again in a minute."
        ) from exc


def run_params(
    lat: float, lon: float, label: str, travel: str, minutes: int, km: float | None, ages: str, business: str,
) -> dict[str, Any]:
    """The survey's query as the web app sends it: minutes for a walk or a drive, km for a road distance (the server
    says what is missing or out of range), and intent 'open' with the business when one is given."""
    params: dict[str, Any] = {
        "lat": f"{lat:.6f}", "lon": f"{lon:.6f}", "label": label, "travel": travel, "ages": ages,
        "intent": "open" if business else "explore",
    }
    if travel != "distance":
        params["minutes"] = minutes
    elif km is not None:
        params["km"] = km
    if business:
        params["business"] = business
    return params


def survey_id(value: str) -> str:
    """A survey's id, also from its link ('https://walkin-app.pages.dev/s/b21ec69b0e92')."""
    value = (value or "").strip()
    found = SURVEY_LINK.search(value)
    run_id = found.group(1) if found else value
    if not RUN_ID.fullmatch(run_id):
        raise WalkinError("A survey id is up to 32 letters, digits and dashes, such as b21ec69b0e92, or its /s/ link.")
    return run_id


def json_of(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def waking(response: httpx.Response) -> bool:
    """Whether the answer means the free server is still waking: the front door's 503 {"waking": true}, or the
    host's own page instead of the API's JSON."""
    if response.status_code not in (502, 503, 504):
        return False
    body = json_of(response)
    if isinstance(body, dict):
        return body.get("waking") is True
    return "json" not in response.headers.get("content-type", "")


def retry_after(response: httpx.Response) -> float:
    """The answer's Retry-After in seconds, 1 to 15; 3 when it gives none."""
    try:
        seconds = float(response.headers.get("retry-after", ""))
    except ValueError:
        return 3.0
    return min(15.0, max(1.0, seconds))


def failure(response: httpx.Response, path: str) -> str:
    """A failed answer in plain words: the server's own message when it sent one."""
    if response.status_code == 429:
        if path == "/api/run":
            return TOO_MANY_SURVEYS
        return "Walk-in is getting too many requests from this address; try again later."
    detail = detail_of(json_of(response))
    if path == "/api/geocode" and response.status_code >= 500:  # Nominatim is slow or down; coordinates still work
        return f"{detail or 'Walk-in could not search for the address right now.'} Give the site's lat and lon instead."
    if detail:
        return detail
    if response.status_code >= 500:
        return f"Walk-in is unavailable right now (HTTP {response.status_code}); try again in a minute."
    return f"Walk-in answered {path} with HTTP {response.status_code}; check WALKIN_URL."


def detail_of(body: Any) -> str | None:
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, str):
        return text(detail)
    if isinstance(detail, list):  # FastAPI's validation errors: the parameter, and what is wrong with it
        problems = [
            f"{item['loc'][-1]}: {item['msg']}" if isinstance(item.get("loc"), list) and item["loc"] else item["msg"]
            for item in detail if isinstance(item, dict) and isinstance(item.get("msg"), str)
        ]
        if problems:
            return f"Walk-in could not read the request: {'; '.join(problems)}."
    return None


def duration(seconds: float) -> str:
    if seconds >= 60 and seconds % 60 == 0:
        whole = int(seconds // 60)
        return f"{whole} minute{'s' if whole > 1 else ''}"
    return f"{seconds:g} seconds"


# ---------- Summaries: only what Walk-in sent, in its own words ----------

def text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def texts(value: Any) -> list[str]:
    """The strings of a list; lists written by the agent are not guaranteed to be lists."""
    return [item.strip() for item in value if isinstance(item, str) and item.strip()] if isinstance(value, list) else []


def short_label(label: Any) -> str | None:
    """'Fort Greene, Brooklyn, Kings County, New York' -> 'Fort Greene, Brooklyn', as the web app names a found site."""
    parts = [part.strip() for part in label.split(",") if part.strip()] if isinstance(label, str) else []
    return ", ".join(parts[:2]) or None


def run_id_of(events: list[tuple[str, Any]]) -> str | None:
    return next((text(data.get("run_id")) for name, data in events
                 if name in ("run", "done") and isinstance(data, dict) and text(data.get("run_id"))), None)


def summarize(
    events: list[tuple[str, Any]], base: str, *, run_id: str | None = None, status: str | None = None,
    stopped: str | None = None,
) -> str:
    """A survey's events as a short report: the site, area and age focus, the verdict on the business tested, the top
    gaps with their evidence, the concepts, and the link to the rest.

    `status` is the saved survey's ('running', 'complete' or 'failed'); `stopped` says why a survey read live ends
    here before the survey did.
    """
    last: dict[str, dict] = {}
    notices: list[str] = []
    for name, data in events:
        if isinstance(data, dict):
            last[name] = data  # each event as last streamed: a survey sends many status events
            message = text(data.get("message"))
            if name == "notice" and message and message not in notices:
                notices.append(message)
    started = last.get("run", {})
    site = started.get("site") if isinstance(started.get("site"), dict) else {}
    catchment = last.get("catchment", {})
    run_id = run_id_of(events) or run_id

    lines = [f"## Walk-in survey: {text(site.get('label')) or 'a storefront'}"]
    area = area_of(started, catchment, site)
    if area:
        lines.append(f"- Area: {area}")
    if started:
        lines.append(f"- Age focus: {text(started.get('ages_label')) or 'everyone'}")
    business = text(site.get("business"))
    if site.get("intent") == "open" and business:
        lines.append(f"- Testing: {business}")
    lines += verdict_lines(last.get("verdict"))
    lines += gap_lines(last.get("gaps"))
    lines += concept_lines(last.get("concepts"))
    if notices:
        lines += ["", *(f"Note: {notice}" for notice in notices)]
    error = text(last.get("error", {}).get("message"))
    if error:
        lines += ["", f"**The survey stopped:** {error}"]
    elif status == "failed":
        lines += ["", "**The survey did not finish:** Walk-in saved it as failed."]
    if stopped and run_id:
        lines += ["", f"**Not finished:** this is what the survey had found when {stopped}. It may still be running at "
                      f"Walk-in: call get_survey(\"{run_id}\") in a minute for the rest, or open the link below."]
    elif status == "running":
        lines += ["", "**Still running:** this is what it has found so far; ask again in a minute."]
    if run_id:
        lines += ["", f"Survey, design sheets and the free launch kit: {base}/s/{run_id}"]
    lines.append(CREDIT)
    return "\n".join(lines)


def area_of(started: dict, catchment: dict, site: dict) -> str | None:
    """'10-minute walk (1.56 km², traced over the street network)'. Surveys saved before drives existed have no
    label: they were walks."""
    minutes = catchment.get("minutes") or site.get("minutes")
    label = text(started.get("area_label")) or text(catchment.get("label")) or (
        f"{minutes}-minute walk" if isinstance(minutes, int) else None
    )
    if not label:
        return None
    size = catchment.get("area_km2")
    details = [f"{size:.2f} km²" if isinstance(size, int | float) else "", SHAPES.get(catchment.get("source"), "")]
    details = [detail for detail in details if detail]
    return f"{label} ({', '.join(details)})" if details else label


def verdict_lines(verdict: Any) -> list[str]:
    if not isinstance(verdict, dict):
        return []
    lines = []
    headline = text(verdict.get("headline"))
    if headline:
        lines.append(f"**Verdict:** {headline}")
    chain = verdict.get("chain")
    line = text(chain.get("line")) if isinstance(chain, dict) else None
    if line:
        lines.append(f"**Chain:** {line}")
    return ["", *lines] if lines else []


def gap_lines(gaps: Any) -> list[str]:
    if not isinstance(gaps, dict):
        return []
    rows = [row for row in gaps.get("rows") or [] if isinstance(row, dict)] if isinstance(gaps.get("rows"), list) else []
    if not rows:
        return ["", "**Top gaps:** none ranked."]
    lines = ["", f"**Top gaps** ({min(TOP_GAPS, len(rows))} of {len(rows)} categories ranked, most missing first)"]
    for number, row in enumerate(rows[:TOP_GAPS], 1):
        reading = text(row.get("reading"))
        lines.append(f"{number}. **{text(row.get('genre')) or 'A category'}**" + (f": {reading}" if reading else ""))
        # The row in plain sentences; rows saved before the sentences existed may carry them as `evidence`.
        lines += [f"   - {line}" for line in texts(row.get("why")) or texts(row.get("evidence"))]
    return lines


def concept_lines(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    concepts = payload.get("concepts") if isinstance(payload.get("concepts"), list) else []
    concepts = [concept for concept in concepts if isinstance(concept, dict) and text(concept.get("name"))]
    lines = [""]
    if concepts:
        lines.append("**Concepts**")
        for number, concept in enumerate(concepts, 1):
            kind = " (wildcard: two loves combined, untested)" if concept.get("wildcard") else ""
            one_liner = text(concept.get("one_liner"))
            lines.append(f"{number}. **{text(concept['name'])}**{kind}" + (f": {one_liner}" if one_liner else ""))
    else:
        note = text(payload.get("note"))
        lines.append("**Concepts:** none." + (f" {note}" if note else ""))
    caution = text(payload.get("caution"))
    if caution:
        lines.append(f"Caution: {caution}")
    return lines


def examples_summary(examples: Any, walkin: Walkin) -> str:
    items = [item for item in examples if isinstance(item, dict) and text(item.get("run_id"))] if isinstance(examples, list) else []
    if not items:
        return "Walk-in lists no finished example surveys right now."
    count = f"{len(items)} finished survey{'s' if len(items) > 1 else ''}"
    lines = [f"## Walk-in examples: {count} anyone can open (opening them costs nothing)"]
    for number, example in enumerate(items, 1):
        run_id = text(example["run_id"])
        area, ages = text(example.get("area")), text(example.get("ages"))
        head = [f"{number}. **{text(example.get('label')) or 'A storefront'}**", area, f"for {ages}" if ages else None]
        lines.append(" · ".join(part for part in [*head, f"run id {run_id}"] if part))
        business = text(example.get("business"))
        if example.get("intent") == "open" and business:
            verdict = text(example.get("verdict"))
            lines.append(f"   - Testing {business}" + (f": {verdict}" if verdict else ""))
        top = texts(example.get("top_gaps"))
        if isinstance(example.get("gaps"), int):
            lines.append(f"   - {example['gaps']} categories ranked" + (f"; most missing: {', '.join(top)}" if top else ""))
        concepts = texts(example.get("concepts"))
        if concepts:
            lines.append(f"   - Concepts: {', '.join(concepts)}")
        lines.append(f"   - Survey: {walkin.link(text(example.get('url')) or f'/s/{run_id}')}")
        kit = example.get("kit") if isinstance(example.get("kit"), dict) else {}
        if text(kit.get("url")):
            name = text(kit.get("name"))
            entry = f"   - Launch kit{f' ({name})' if name else ''}: {walkin.link(text(kit['url']))}"
            report = text(kit.get("report_url"))
            lines.append(entry + (f" · Report: {walkin.link(report)}" if report else ""))
    lines += ["", "get_survey reads any of them in full: its top gaps with their evidence, and its concepts.", CREDIT]
    return "\n".join(lines)


# ---------- The MCP server ----------

INSTRUCTIONS = """Walk-in surveys an empty storefront for someone deciding what to open there. It traces the real walk \
or drive area, reads Qloo's taste data for the people in it, ranks the kinds of places the area is missing against the \
areas around it, and designs business concepts from that evidence; its web page then builds design sheets and a free \
launch kit.

- list_examples: finished surveys anyone can open, free. Good for showing what Walk-in gives.
- survey_storefront: surveys a site (one to three minutes). It spends Qloo and AI quota and Walk-in allows a few per \
hour from one address, so run it once per site and brief.
- get_survey: reads a survey again by its run id or link, free; also the rest of one that was still running.

Report what the tools return in their words: every number and sentence comes from Qloo's data and Walk-in's rules, \
so add none of your own, and pass on the survey link."""

# Warnings only on stderr: at INFO, FastMCP and httpx would log every request.
mcp = FastMCP("Walk-in", instructions=INSTRUCTIONS, website_url=DEFAULT_URL, log_level="WARNING")


def connect() -> Walkin:
    """The Walk-in API the tools call, with WALKIN_URL read on each call; tests swap it for one on a mock transport."""
    return Walkin()


@mcp.tool(
    title="Survey a storefront",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True),
    structured_output=False,
)
async def survey_storefront(
    place: Annotated[str | None, Field(
        description="The storefront's address or neighborhood, such as '120 Bedford Ave, Brooklyn' or 'Zamalek, Cairo'. "
                    "Walk-in's address search takes its first match, and lat and lon are then ignored.",
    )] = None,
    lat: Annotated[float | None, Field(description="The site's latitude, when no place is given.")] = None,
    lon: Annotated[float | None, Field(description="The site's longitude, when no place is given.")] = None,
    travel: Annotated[Travel, Field(
        description="How customers come: on foot ('walk'), by car ('drive'), or from within a road distance ('distance').",
    )] = "walk",
    minutes: Annotated[int, Field(description="The walk or the drive, 5 to 60 minutes (travel 'walk' or 'drive').")] = 10,
    km: Annotated[float | None, Field(description="The road distance, 1 to 100 km (travel 'distance' only).")] = None,
    ages: Annotated[Ages, Field(
        description="Who the owner wants to serve: the age group whose taste ranks the gaps, or 'all' for everyone.",
    )] = "all",
    business: Annotated[str | None, Field(
        description="A business the owner wants to open, such as 'a bakery' or 'Starbucks': the survey judges it against "
                    "the area's gaps first. Leave it out to ask what the area is missing.",
    )] = None,
    ctx: Context | None = None,
) -> str:
    """Survey an empty storefront with Walk-in: what the area around it is missing, and what to open there.

    Walk-in traces the real walk or drive area over the streets, reads Qloo's taste data for the people in it, ranks
    the kinds of places the area lacks against the areas around it, and designs concepts from that evidence. With a
    business, it first judges that idea (and counts a chain's own stores nearby). Returns the area, the top gaps with
    their evidence, the concepts and a link to the survey's design sheets and free launch kit.

    A survey takes one to three minutes, a minute more when Walk-in's free server is waking up. Each one spends Qloo
    and AI quota and Walk-in allows a few per hour from one address: run it once per site and brief, and read it again
    with get_survey.
    """
    return await connect().survey(
        place=place, lat=lat, lon=lon, travel=travel, minutes=minutes, km=km, ages=ages, business=business,
        progress=Progress(ctx),
    )


@mcp.tool(
    title="List finished example surveys",
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True),
    structured_output=False,
)
async def list_examples() -> str:
    """List Walk-in's finished example surveys, which anyone can open for free: each site and area, what it found
    missing, its concepts, and links to the survey, its launch kit and its printable report. Use it to show what
    Walk-in gives before running a survey."""
    return await connect().examples()


@mcp.tool(
    title="Get a survey",
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True),
    structured_output=False,
)
async def get_survey(
    run_id: Annotated[str, Field(
        description="The survey's run id, such as 'b21ec69b0e92', or its link (https://walkin-app.pages.dev/s/...).",
    )],
) -> str:
    """Read a Walk-in survey again by its run id: its area, age focus, top gaps with their evidence, concepts and, for a
    business tested, the verdict. Free: it reads what Walk-in saved. A survey still running shows what it found so far."""
    return await connect().record(run_id)


def main() -> None:
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
