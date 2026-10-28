"""Who may keep a copy of an API response: the Cache-Control header, the one contract with the front door.

Finished surveys, ready kits, the presets, the public settings and the examples list are the same for every visitor
and do not change, so browsers and the front door (frontend/functions, Cloudflare) may keep them; the examples' for a
day, since judges and visitors open them most. Everything else is no-store: the survey stream, running surveys,
building kits, the signed-in user and their places, every write, the health check and every error. The front door
caches only a GET answered 200 with `public` and an s-maxage, without Set-Cookie, keyed by the URL alone, so a public
response never depends on who asks (no session, cookie or address in it) and never sets a cookie (guard).

Only what belongs to no visitor (the presets, the public settings, the examples list, the examples' surveys and kits)
carries stale-if-error (RFC 5861): the front door may keep a stale copy of it for a week and serve it while the backend
is waking, down or erroring. Anyone's own survey or kit carries none, so no stale copy of it exists anywhere: its edge
copy lasts its s-maxage at most, and deleting an account stops its share links working within about ten minutes, as
the privacy page promises.
"""
from __future__ import annotations

from fastapi import Request, Response

from .config import settings

STALE_IF_ERROR = "stale-if-error=604800"  # a week: what the front door may serve while the backend is down
STATIC = f"public, max-age=300, s-maxage=3600, {STALE_IF_ERROR}"  # GET /api/presets and /api/config: change with a deploy
EXAMPLES = f"public, max-age=60, s-maxage=300, {STALE_IF_ERROR}"  # GET /api/examples
EXAMPLE_RUN = f"public, max-age=3600, s-maxage=86400, {STALE_IF_ERROR}"  # a finished survey that is one of the examples
FINISHED_RUN = "public, max-age=60, s-maxage=600"  # anyone's own finished survey: no stale copy, gone within 10 minutes
EXAMPLE_KIT = f"public, max-age=600, s-maxage=86400, {STALE_IF_ERROR}"  # a ready kit of an example survey
READY_KIT = "public, max-age=60, s-maxage=600"  # anyone's own ready kit: no stale copy, gone within 10 minutes
NO_STORE = "no-store"

FINISHED = frozenset({"complete", "failed"})
CACHEABLE_METHODS = frozenset({"GET", "HEAD"})


def for_run(run_id: str, status: str, *, settled: bool = True) -> str:
    """A survey's record: public once it has finished (it never changes again) and is settled (a survey still running
    in this process has streamed its last event but is saved first), the examples' for longer."""
    if status not in FINISHED or not settled:
        return NO_STORE
    return EXAMPLE_RUN if run_id in settings.examples else FINISHED_RUN


def for_kit(survey_id: str, status: str, *, settled: bool = True) -> str:
    """A kit's page: public once it is ready and settled (no street map may still be added to it, app.kits), the
    examples' kits for longer."""
    if status != "ready" or not settled:
        return NO_STORE
    return EXAMPLE_KIT if survey_id in settings.examples else READY_KIT


def is_public(header: str) -> bool:
    """Whether a Cache-Control header lets shared caches (the front door) keep the response."""
    return "public" in (part.strip().lower() for part in header.split(","))


def guard(request: Request, response: Response) -> None:
    """The last word on an API response's Cache-Control (the security middleware calls it once the cookies are set):
    no-store unless its route made it public, and never public for anything but a 200 to a GET, nor with a cookie."""
    if not request.url.path.startswith("/api/"):
        return
    header = response.headers.get("cache-control")
    shareable = (
        request.method in CACHEABLE_METHODS and response.status_code == 200 and "set-cookie" not in response.headers
    )
    if not header or (is_public(header) and not shareable):
        response.headers["Cache-Control"] = NO_STORE
