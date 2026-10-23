"""Accounts: Sign in with Google, sessions, the browser's device id and the origin check for the API's unsafe methods.

A Google ID token is trusted only once its signature checks out against Google's published keys (JWKS), and its
issuer, audience (our client ID), expiry and verified email do too. A session is a random token in an HttpOnly cookie;
the database keeps only its SHA-256, so a leaked database signs nobody in. Cookies are queued on the request and set on
whatever response goes out (the security middleware in app.main), errors included.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import secrets
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Annotated, Any, Protocol

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, Response

from .config import origin_of, settings

log = logging.getLogger("walkin")

GOOGLE_CERTS = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")
SESSION_COOKIE = "walkin_session"
DEVICE_COOKIE = "walkin_device"
DEVICE_DAYS = 400  # the longest a browser keeps a cookie
DEVICE_ID = re.compile(r"[0-9a-f]{32}")
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Seconds a token's times may be off by, for clocks that differ between Google and this server.
LEEWAY = 60
# Google's keys are kept this long when its answer gives no max-age, and fetched again at most this often when a token
# names a key we do not have (Google rotates its keys).
DEFAULT_KEY_AGE = 3600.0
REFETCH_AFTER = 60.0
MAX_AGE = re.compile(r"(?:^|[,\s])max-age=(\d+)", re.IGNORECASE)


class TokenError(ValueError):
    """A sign-in token that cannot be trusted; the message says why, in plain words."""


class KeysUnavailable(RuntimeError):
    """Google's keys could not be fetched, so no token can be checked right now."""


class KeySource(Protocol):
    async def get(self, kid: str) -> jwt.PyJWK | None: ...


class GoogleKeys:
    """Google's public keys for ID tokens, fetched from its JWKS endpoint and kept as long as its Cache-Control allows.

    One instance serves the app; concurrent sign-ins share one fetch. `http_client` and `clock` are for tests.
    """

    def __init__(
        self, url: str = GOOGLE_CERTS, http_client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic, timeout: float = 10.0,
    ) -> None:
        self.url = url
        self._http = http_client
        self._own_http = http_client is None
        self._clock = clock
        self._timeout = timeout
        self._keys: dict[str, jwt.PyJWK] = {}
        self._until = 0.0
        self._fetched: float | None = None
        self._lock: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None

    async def get(self, kid: str) -> jwt.PyJWK | None:
        """The key with this id: from memory while fresh, else after fetching Google's keys again."""
        if self._clock() < self._until and kid in self._keys:
            return self._keys[kid]
        async with self._guard():
            now = self._clock()
            stale = now >= self._until
            unknown = kid not in self._keys and (self._fetched is None or now - self._fetched >= REFETCH_AFTER)
            if stale or unknown:
                await self._fetch()
        return self._keys.get(kid)

    async def aclose(self) -> None:
        if self._own_http and self._http is not None:
            await self._http.aclose()

    def _guard(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop is not loop:
            self._lock, self._lock_loop = asyncio.Lock(), loop
        return self._lock

    async def _fetch(self) -> None:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self._timeout)
        self._fetched = self._clock()
        try:
            response = await self._http.get(self.url, timeout=self._timeout)
            response.raise_for_status()
            found = response.json().get("keys")
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            if self._keys and self._clock() < self._until:
                return
            raise KeysUnavailable(f"Google's sign-in keys could not be fetched ({type(exc).__name__})") from exc
        keys = {}
        for data in found if isinstance(found, list) else []:
            if not isinstance(data, dict) or not isinstance(data.get("kid"), str) or data.get("use", "sig") != "sig":
                continue
            try:
                keys[data["kid"]] = jwt.PyJWK(data)
            except jwt.PyJWTError:
                log.warning("Skipping a Google signing key that cannot be read")
        if not keys:
            raise KeysUnavailable("Google's answer had no signing keys")
        self._keys = keys
        self._until = self._fetched + cache_seconds(response.headers)


def cache_seconds(headers: httpx.Headers) -> float:
    """How long an answer stays fresh: Cache-Control's max-age minus its Age, else DEFAULT_KEY_AGE."""
    found = MAX_AGE.search(headers.get("cache-control", ""))
    if not found:
        return DEFAULT_KEY_AGE
    try:
        age = float(headers.get("age", 0))
    except ValueError:
        age = 0.0
    return max(0.0, float(found.group(1)) - age)


async def verify_google_token(credential: str, client_id: str, keys: KeySource) -> dict[str, Any]:
    """The claims of a Google ID token from Google Identity Services, once its signature (RS256, one of Google's
    current keys), issuer, audience, expiry and verified email check out; TokenError otherwise."""
    if not isinstance(credential, str) or not credential or len(credential) > 8192:
        raise TokenError("That is not a Google sign-in.")
    try:
        header = jwt.get_unverified_header(credential)
    except jwt.PyJWTError as exc:
        raise TokenError("That is not a Google sign-in.") from exc
    kid = header.get("kid")
    if header.get("alg") != "RS256" or not isinstance(kid, str):
        raise TokenError("The sign-in token is not signed the way Google signs them.")
    key = await keys.get(kid)
    if key is None:
        raise TokenError("The sign-in token was not signed with one of Google's keys.")
    try:
        claims = jwt.decode(
            credential, key.key, algorithms=["RS256"], audience=client_id, issuer=GOOGLE_ISSUERS, leeway=LEEWAY,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("The sign-in has expired. Sign in again.") from exc
    except jwt.InvalidAudienceError as exc:
        raise TokenError("The sign-in was meant for another app.") from exc
    except jwt.InvalidIssuerError as exc:
        raise TokenError("The sign-in did not come from Google.") from exc
    except jwt.InvalidSignatureError as exc:
        raise TokenError("The sign-in token's signature is not Google's.") from exc
    except jwt.PyJWTError as exc:
        raise TokenError("The sign-in token could not be checked.") from exc
    if claims.get("email_verified") not in (True, "true") or not isinstance(claims.get("email"), str):
        raise TokenError("Google has not verified this account's email address.")
    return claims


# Cookies

def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    """32 random bytes, base64url."""
    return secrets.token_urlsafe(32)


def secure(request: Request) -> bool:
    """Whether the site is served over https, so cookies are marked Secure."""
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return settings.hosted or forwarded == "https" or request.url.scheme == "https"


def queue_cookie(request: Request, name: str, value: str | None, max_age: int = 0) -> None:
    """Sets (or with None, clears) a cookie on the response to this request, whatever that response turns out to be."""
    cookies = getattr(request.state, "cookies", None)
    if cookies is None:
        cookies = request.state.cookies = {}
    cookies[name] = (value, max_age)


def apply_cookies(request: Request, response: Response) -> None:
    for name, (value, max_age) in (getattr(request.state, "cookies", None) or {}).items():
        options = {"path": "/", "httponly": True, "samesite": "lax", "secure": secure(request)}
        if value is None:
            response.delete_cookie(name, **options)
        else:
            response.set_cookie(name, value, max_age=max_age, **options)


async def start_session(request: Request, user: dict) -> None:
    """Signs the user in: a new session (any earlier one in this browser ends), its cookie, and the surveys this
    browser ran before are now theirs."""
    state = request.app.state
    earlier = request.cookies.get(SESSION_COOKIE)
    if earlier:
        await state.accounts.close_session(token_hash(earlier))
    token = new_token()
    days = settings.session_days
    await state.accounts.open_session(user["id"], token_hash(token), state.now() + timedelta(days=days))
    queue_cookie(request, SESSION_COOKIE, token, days * 86400)
    request.state.user = user
    device = request.cookies.get(DEVICE_COOKIE, "")
    if DEVICE_ID.fullmatch(device):
        await state.accounts.attach_device(user["id"], device)


async def end_session(request: Request) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await request.app.state.accounts.close_session(token_hash(token))
    queue_cookie(request, SESSION_COOKIE, None)
    request.state.user = None


async def delete_account(request: Request, user: dict) -> None:
    """Deletes the user, every session they have and the surveys in their My places (design sheets go with them),
    drops those surveys from memory, and makes this browser forget the session and its device id."""
    state = request.app.state
    for run_id in await state.accounts.delete(user["id"]):
        state.runs.forget(run_id)
    queue_cookie(request, SESSION_COOKIE, None)
    queue_cookie(request, DEVICE_COOKIE, None)
    request.state.user = None


async def current_user(request: Request) -> dict | None:
    """The signed-in user, or None. Using a session renews it to SESSION_DAYS from now, at most once a day."""
    if hasattr(request.state, "user"):
        return request.state.user
    user = None
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        state = request.app.state
        found = await state.accounts.session(token_hash(token), state.now())
        if found is None:
            queue_cookie(request, SESSION_COOKIE, None)
        else:
            user, expires = found
            renewed: datetime = state.now() + timedelta(days=settings.session_days)
            if renewed - expires >= timedelta(days=1):
                await state.accounts.extend_session(token_hash(token), renewed)
                queue_cookie(request, SESSION_COOKIE, token, settings.session_days * 86400)
    request.state.user = user
    return user


async def require_user(request: Request) -> dict:
    user = await current_user(request)
    if user is None:
        raise HTTPException(401, "Sign in first.")
    return user


# An endpoint parameter for the signed-in user; 401 when nobody is signed in.
SignedIn = Annotated[dict, Depends(require_user)]


def device_id(request: Request) -> str:
    """This browser's id from its walkin_device cookie; a new one (and its cookie) when it has none."""
    device = request.cookies.get(DEVICE_COOKIE, "")
    if DEVICE_ID.fullmatch(device):
        return device
    device = secrets.token_hex(16)
    queue_cookie(request, DEVICE_COOKIE, device, DEVICE_DAYS * 86400)
    return device


def public_user(user: dict) -> dict:
    return {"id": user["id"], "email": user["email"], "name": user["name"], "picture": user.get("picture")}


# The origin check

def own_origin(request: Request) -> str | None:
    host = request.headers.get("host")
    if not host:
        return None
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return f"{forwarded or request.url.scheme}://{host}".lower()


def origin_allowed(request: Request) -> bool:
    """Whether a request may go on: safe methods and paths outside the API always may; an unsafe API call with an
    Origin header must come from PUBLIC_URL, the server itself or ALLOWED_ORIGINS."""
    if request.method not in UNSAFE_METHODS or not request.url.path.startswith("/api/"):
        return True
    origin = request.headers.get("origin")
    if origin is None:
        return True
    found = origin_of(origin)
    return found is not None and (found in settings.trusted_origins or found == own_origin(request))
