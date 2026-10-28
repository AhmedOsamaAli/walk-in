"""PayPal REST client (Orders v2, Payments v2, Payouts v1, Webhooks v1) and pure readers of its answers.

The sandbox until PAYPAL_ENV=live (settings.paypal_api_base). Every POST carries a PayPal-Request-Id, so a retry after
a timeout never charges twice, and asks for the whole resource back (Prefer: return=representation). Orders set
the payer's experience in payment_source.paypal.experience_context, where PayPal moved it from the deprecated
application_context. Payouts are made safe by their sender_batch_id instead, which PayPal never pays twice within 30
days: it refuses any repeat, even with the same request id, and its refusal links to the batch it made (duplicate_payout).
Money is a string or a Decimal, never a float. Secrets and access tokens are never logged.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

log = logging.getLogger("walkin")

# An authorization holds the money for 29 days; a capture is surest in its first 3, the honor period. After that, one
# reauthorization (from day 4 to day 29) renews the hold under a new authorization ID.
AUTHORIZATION_PERIOD = timedelta(days=29)
HONOR_PERIOD = timedelta(days=3)
# Currencies PayPal takes in whole units.
ZERO_DECIMAL = frozenset({"HUF", "JPY", "TWD"})
# A token is renewed this many seconds before PayPal says it expires (a tenth of its life when that is shorter).
TOKEN_MARGIN = 300.0
# What the pledges and the payouts listen to: pledges approved, holds placed or voided, payments completed, pending,
# denied, refunded or reversed, and each payout batch and item as PayPal processes it.
PAYOUT_BATCH_EVENTS = (
    "PAYMENT.PAYOUTSBATCH.DENIED",
    "PAYMENT.PAYOUTSBATCH.PROCESSING",
    "PAYMENT.PAYOUTSBATCH.SUCCESS",
)
PAYOUT_ITEM_EVENTS = (
    "PAYMENT.PAYOUTS-ITEM.BLOCKED",
    "PAYMENT.PAYOUTS-ITEM.CANCELED",
    "PAYMENT.PAYOUTS-ITEM.DENIED",
    "PAYMENT.PAYOUTS-ITEM.FAILED",
    "PAYMENT.PAYOUTS-ITEM.HELD",
    "PAYMENT.PAYOUTS-ITEM.REFUNDED",
    "PAYMENT.PAYOUTS-ITEM.RETURNED",
    "PAYMENT.PAYOUTS-ITEM.SUCCEEDED",
    "PAYMENT.PAYOUTS-ITEM.UNCLAIMED",
)
WEBHOOK_EVENTS = (
    "CHECKOUT.ORDER.APPROVED",
    "PAYMENT.CAPTURE.COMPLETED",
    "PAYMENT.CAPTURE.PENDING",
    "PAYMENT.CAPTURE.DENIED",
    "PAYMENT.CAPTURE.DECLINED",
    "PAYMENT.CAPTURE.REFUNDED",
    "PAYMENT.CAPTURE.REVERSED",
    "PAYMENT.AUTHORIZATION.CREATED",
    "PAYMENT.AUTHORIZATION.VOIDED",
    *PAYOUT_BATCH_EVENTS,
    *PAYOUT_ITEM_EVENTS,
)
# A payout batch's and a payout item's status at PayPal, as the owner sees the payout: pending, paid or failed.
PAYOUT_BATCH_STATUS = {"PENDING": "pending", "PROCESSING": "pending", "SUCCESS": "paid", "DENIED": "failed",
                       "CANCELED": "failed"}
PAYOUT_ITEM_STATUS = {
    "SUCCESS": "paid", "PENDING": "pending", "UNCLAIMED": "pending", "ONHOLD": "pending", "NEW": "pending",
    "FAILED": "failed", "RETURNED": "failed", "BLOCKED": "failed", "REFUNDED": "failed", "REVERSED": "failed",
    "DENIED": "failed", "CANCELED": "failed",
}
# The headers PayPal signs a webhook delivery with, under the names verify-webhook-signature takes them.
WEBHOOK_HEADERS = {
    "auth_algo": "paypal-auth-algo",
    "cert_url": "paypal-cert-url",
    "transmission_id": "paypal-transmission-id",
    "transmission_sig": "paypal-transmission-sig",
    "transmission_time": "paypal-transmission-time",
}
# PayPal IDs are letters, digits and dashes, at most 64 here as in the columns that keep them (app.db.tables); nothing
# else may reach a URL path.
RESOURCE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
REQUEST_KEYS = uuid.uuid5(uuid.NAMESPACE_URL, "walk-in:paypal")


class PayPalError(RuntimeError):
    """An error answer from PayPal (status 0 when PayPal could not be reached), with the error's name, its issue codes
    and the debug ID PayPal support asks for."""

    def __init__(
        self, status: int, name: str, message: str, debug_id: str | None = None, details: list[dict] | None = None,
        links: list[dict] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.name = name
        self.message = message
        self.debug_id = debug_id
        self.details = details or []
        self.links = links or []  # PayPal's links, such as the original payout of a duplicate sender_batch_id

    @property
    def issues(self) -> list[str]:
        """PayPal's fine-grained codes, such as INSTRUMENT_DECLINED or AUTHORIZATION_ALREADY_CAPTURED."""
        return [detail["issue"] for detail in self.details if isinstance(detail.get("issue"), str)]

    def has(self, *codes: str) -> bool:
        """Whether the error's name or one of its issues is among `codes`."""
        found = {self.name, *self.issues}
        return any(code in found for code in codes)

    @property
    def retryable(self) -> bool:
        """Whether the same request can succeed later: no answer, a timeout, a request still in progress, a rate limit
        or a PayPal outage."""
        return self.status in (0, 408, 409, 429) or self.status >= 500

    def __str__(self) -> str:
        issues = f" ({', '.join(self.issues)})" if self.issues else ""
        debug = f" [debug_id {self.debug_id}]" if self.debug_id else ""
        return f"PayPal {self.status or 'unreachable'} {self.name}{issues}: {self.message}{debug}"


class PayPalClient:
    """Async PayPal REST client. One instance serves the app: it caches the OAuth2 access token and renews it shortly
    before it expires, one renewal at a time however many requests wait for it."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        api_base: str,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 20,
        *,
        retries: int = 2,
        backoff: float = 0.5,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """`retries` repeats requests that failed for reasons that pass (network, 409, 429, 5xx), waiting `backoff`
        seconds and doubling; `clock` is for tests."""
        self._client_id = client_id
        self._client_secret = client_secret
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self._clock = clock
        self._own_http = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout)
        self._token: str | None = None
        self._token_until = 0.0
        self._token_lock: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None

    def __repr__(self) -> str:
        return f"PayPalClient(api_base={self.api_base!r})"

    @property
    def configured(self) -> bool:
        return bool(self._client_id and self._client_secret)

    async def aclose(self) -> None:
        """Closes the HTTP client this instance made; one passed in belongs to the caller."""
        if self._own_http:
            await self._http.aclose()

    # Orders v2

    async def create_order(
        self,
        *,
        intent: str,
        amount: str | Decimal,
        currency: str,
        description: str,
        custom_id: str,
        reference_id: str | None = None,
        brand_name: str = "Walk-in",
        request_id: str,
        return_url: str | None = None,
        cancel_url: str | None = None,
    ) -> dict:
        """An order for the buyer to approve: CAPTURE collects on approval (Pay Now), AUTHORIZE only holds the money
        (Continue). The buyer approves it in PayPal's buttons with the order's id, or at approval_url(order)."""
        intent = intent.upper()
        if intent not in ("CAPTURE", "AUTHORIZE"):
            raise ValueError(f"Unknown intent {intent!r}: use CAPTURE or AUTHORIZE.")
        if not custom_id or len(custom_id) > 255:  # PayPal's limit; cutting it would break reconciliation
            raise ValueError("custom_id must be 1 to 255 characters.")
        if reference_id is not None and not 1 <= len(reference_id) <= 256:
            raise ValueError("reference_id must be 1 to 256 characters.")
        currency = currency.upper()
        unit: dict[str, Any] = {
            "amount": {"currency_code": currency, "value": money(amount, currency)},
            "custom_id": custom_id,
        }
        text = " ".join(description.split())
        if text:
            unit["description"] = text[:127]  # PayPal keeps 127 characters of it
        if reference_id:
            unit["reference_id"] = reference_id
        context: dict[str, Any] = {
            "brand_name": brand_name[:127],
            "shipping_preference": "NO_SHIPPING",
            "user_action": "PAY_NOW" if intent == "CAPTURE" else "CONTINUE",
            # Cards, balance and instant bank transfers only, so a capture is never left pending on an eCheck.
            "payment_method_preference": "IMMEDIATE_PAYMENT_REQUIRED",
        }
        if return_url:
            context["return_url"] = return_url
        if cancel_url:
            context["cancel_url"] = cancel_url
        body = {"intent": intent, "purchase_units": [unit], "payment_source": {"paypal": {"experience_context": context}}}
        return await self._call("POST", "/v2/checkout/orders", body=body, request_id=request_id)

    async def get_order(self, order_id: str) -> dict:
        return await self._call("GET", f"/v2/checkout/orders/{_resource(order_id)}")

    async def capture_order(self, order_id: str, request_id: str) -> dict:
        """Collects an approved CAPTURE order; the answer is the order with its capture."""
        return await self._call(
            "POST", f"/v2/checkout/orders/{_resource(order_id)}/capture", body={}, request_id=request_id
        )

    async def authorize_order(self, order_id: str, request_id: str) -> dict:
        """Holds the money of an approved AUTHORIZE order; the answer is the order with its authorization."""
        return await self._call(
            "POST", f"/v2/checkout/orders/{_resource(order_id)}/authorize", body={}, request_id=request_id
        )

    # Payments v2

    async def capture_authorization(
        self,
        authorization_id: str,
        request_id: str,
        amount: str | Decimal | None = None,
        final_capture: bool = True,
        *,
        currency: str | None = None,
    ) -> dict:
        """Collects held money: all of it, or `amount` in `currency`. The answer is the capture."""
        body: dict[str, Any] = {"final_capture": final_capture}
        if amount is not None:
            body["amount"] = money_object(amount, currency)
        return await self._call(
            "POST", f"/v2/payments/authorizations/{_resource(authorization_id)}/capture", body=body,
            request_id=request_id,
        )

    async def void_authorization(self, authorization_id: str, request_id: str) -> dict:
        """Releases held money. A reauthorization cannot be voided: void the original authorization instead."""
        return await self._call(
            "POST", f"/v2/payments/authorizations/{_resource(authorization_id)}/void", request_id=request_id
        )

    async def reauthorize_authorization(
        self, authorization_id: str, request_id: str, amount: str | Decimal | None = None, *, currency: str | None = None,
    ) -> dict:
        """Renews a hold that is past its 3-day honor period. The answer is a new authorization, with a new ID, to
        capture instead of the original."""
        body = {"amount": money_object(amount, currency)} if amount is not None else {}
        return await self._call(
            "POST", f"/v2/payments/authorizations/{_resource(authorization_id)}/reauthorize", body=body,
            request_id=request_id,
        )

    async def get_authorization(self, authorization_id: str) -> dict:
        return await self._call("GET", f"/v2/payments/authorizations/{_resource(authorization_id)}")

    async def get_capture(self, capture_id: str) -> dict:
        """A capture as PayPal has it now: its status and, once completed, its seller_receivable_breakdown."""
        return await self._call("GET", f"/v2/payments/captures/{_resource(capture_id)}")

    async def refund_capture(
        self,
        capture_id: str,
        request_id: str,
        amount: str | Decimal | None = None,
        note: str | None = None,
        *,
        currency: str | None = None,
    ) -> dict:
        """Returns collected money: all of it, or `amount` in `currency`. `note` reaches the payer."""
        body: dict[str, Any] = {}
        if amount is not None:
            body["amount"] = money_object(amount, currency)
        if note and note.strip():
            body["note_to_payer"] = " ".join(note.split())[:255]
        return await self._call(
            "POST", f"/v2/payments/captures/{_resource(capture_id)}/refund", body=body, request_id=request_id
        )

    # Payouts v1

    async def create_payout(
        self,
        *,
        sender_batch_id: str,
        receiver: str,
        amount: str | Decimal,
        currency: str,
        note: str,
        email_subject: str,
        email_message: str,
        sender_item_id: str | None = None,
        request_id: str,
    ) -> dict:
        """Sends `amount` to one PayPal account by its email: a batch of one item. PayPal pays a sender_batch_id once
        within 30 days, and answers a repeated request id with its first answer, so sending again is safe. The answer
        is the batch header (payout_batch_id, batch_status PENDING when it passed PayPal's first checks)."""
        if not sender_batch_id or len(sender_batch_id) > 256:
            raise ValueError("sender_batch_id must be 1 to 256 characters.")
        if not receiver or len(receiver) > 127:
            raise ValueError("The receiver's email must be 1 to 127 characters.")
        code = currency.upper()
        item: dict[str, Any] = {
            "recipient_type": "EMAIL",
            # Payouts write money as {"currency", "value"}, unlike Orders and Payments ("currency_code").
            "amount": {"currency": code, "value": money(amount, code)},
            "receiver": receiver,
            "note": " ".join(note.split())[:4000],
            "sender_item_id": (sender_item_id or sender_batch_id)[:63],
        }
        body = {
            "sender_batch_header": {
                "sender_batch_id": sender_batch_id,
                "recipient_type": "EMAIL",
                "email_subject": " ".join(email_subject.split())[:255],
                "email_message": " ".join(email_message.split())[:1000],
            },
            "items": [item],
        }
        return await self._call("POST", "/v1/payments/payouts", body=body, request_id=request_id)

    async def get_payout_batch(self, payout_batch_id: str) -> dict:
        """A payout batch with its items, as PayPal processes them."""
        return await self._call("GET", f"/v1/payments/payouts/{_resource(payout_batch_id)}")

    async def get_payout_item(self, payout_item_id: str) -> dict:
        return await self._call("GET", f"/v1/payments/payouts-item/{_resource(payout_item_id)}")

    # Webhooks v1

    async def verify_webhook_signature(
        self, headers: Mapping[str, str], event: Mapping[str, Any] | str | bytes, webhook_id: str,
    ) -> bool:
        """Whether PayPal confirms that a webhook delivery is genuine (a postback to verify-webhook-signature).

        Pass the raw request body as `event` when you can: PayPal checks the event exactly as it sent it, and JSON
        parsed and written again can fail. False when a signature header is missing or PayPal finds the request
        malformed; an outage raises PayPalError, so the delivery fails and PayPal sends it again later. Simulator
        (mock) events cannot be verified this way.
        """
        lowered = {str(key).lower(): str(value).strip() for key, value in headers.items()}
        fields = {field: lowered.get(header, "") for field, header in WEBHOOK_HEADERS.items()}
        if not webhook_id or not all(fields.values()):
            return False
        if isinstance(event, bytes | bytearray):
            try:
                raw = bytes(event).decode("utf-8")
            except UnicodeDecodeError:
                return False
        elif isinstance(event, str):
            raw = event
        else:
            raw = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        try:
            if not isinstance(json.loads(raw), dict):
                return False
        except ValueError:
            return False
        # The event goes back byte for byte; only the envelope around it is written here.
        head = json.dumps({**fields, "webhook_id": webhook_id})
        body = f'{head[:-1]}, "webhook_event": {raw.strip()}}}'
        try:
            data = await self._call("POST", "/v1/notifications/verify-webhook-signature", raw=body.encode("utf-8"))
        except PayPalError as exc:
            if exc.status in (400, 422):
                return False
            raise
        return data.get("verification_status") == "SUCCESS"

    async def create_webhook(
        self, url: str, event_types: Iterable[str] = WEBHOOK_EVENTS, request_id: str | None = None,
    ) -> dict:
        """Subscribes `url` (HTTPS) to `event_types`. The answer's id is the PAYPAL_WEBHOOK_ID to verify with."""
        if not url.startswith("https://"):
            raise ValueError("PayPal only delivers webhooks to HTTPS addresses.")
        names = list(dict.fromkeys(event_types))
        if not names:
            raise ValueError("Name at least one event type.")
        body = {"url": url, "event_types": [{"name": name} for name in names]}
        return await self._call("POST", "/v1/notifications/webhooks", body=body, request_id=request_id)

    async def list_webhooks(self) -> list[dict]:
        """The app's webhooks, each with its id, url and event types."""
        data = await self._call("GET", "/v1/notifications/webhooks", params={"anchor_type": "APPLICATION"})
        return [hook for hook in data.get("webhooks") or [] if isinstance(hook, dict)]

    async def update_webhook_events(self, webhook_id: str, event_types: Iterable[str] = WEBHOOK_EVENTS) -> dict:
        """Subscribes an existing webhook to exactly `event_types`."""
        names = list(dict.fromkeys(event_types))
        if not names:
            raise ValueError("Name at least one event type.")
        body = [{"op": "replace", "path": "/event_types", "value": [{"name": name} for name in names]}]
        return await self._call("PATCH", f"/v1/notifications/webhooks/{_resource(webhook_id)}", body=body)

    # Transport

    def _lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._token_lock is None or self._lock_loop is not loop:
            self._token_lock, self._lock_loop = asyncio.Lock(), loop
        return self._token_lock

    async def _access_token(self) -> str:
        """The cached token while it is fresh, else a new one; concurrent callers share a single renewal."""
        if self._token and self._clock() < self._token_until:
            return self._token
        async with self._lock():
            if self._token and self._clock() < self._token_until:
                return self._token
            if not self.configured:
                raise PayPalError(401, "NOT_CONFIGURED", "PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET are not set.")
            data = await self._send(
                "POST", "/v1/oauth2/token", content=b"grant_type=client_credentials",
                headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
                auth=(self._client_id, self._client_secret),
            )
            token = data.get("access_token")
            if not isinstance(token, str) or not token:
                raise PayPalError(502, "INVALID_TOKEN_RESPONSE", "PayPal's token answer had no access token.")
            try:
                life = max(0.0, float(data.get("expires_in") or 0))
            except (TypeError, ValueError):
                life = 0.0
            self._token = token
            self._token_until = self._clock() + life - min(TOKEN_MARGIN, life / 10)
            return token

    def _forget_token(self, token: str) -> None:
        if self._token == token:  # another request may have renewed it already
            self._token, self._token_until = None, 0.0

    async def _call(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        raw: bytes | None = None,
        request_id: str | None = None,
        params: dict[str, str] | None = None,
    ) -> dict:
        """An API call with the cached token, renewed once when PayPal no longer accepts it."""
        headers = {"Accept": "application/json"}
        if method == "POST":
            if request_id is not None and not 1 <= len(request_id) <= 108:
                raise ValueError("PayPal-Request-Id must be 1 to 108 characters.")
            headers["PayPal-Request-Id"] = request_id or str(uuid.uuid4())
            headers["Prefer"] = "return=representation"
        content = raw if raw is not None else (json.dumps(body).encode("utf-8") if body is not None else None)
        if content is not None:
            headers["Content-Type"] = "application/json"
        renewed = False
        while True:
            try:
                token = await self._access_token()
            except PayPalError as exc:
                log.warning("PayPal token request failed: %s", exc)
                raise
            try:
                return await self._send(
                    method, path, content=content, params=params, headers={**headers, "Authorization": f"Bearer {token}"}
                )
            except PayPalError as exc:
                if exc.status == 401 and not renewed:
                    renewed = True
                    self._forget_token(token)
                    continue
                # Declines and "already done" answers are business as usual; outages and bad credentials are not.
                level = logging.WARNING if exc.retryable or exc.status in (401, 403) else logging.INFO
                log.log(level, "PayPal %s %s failed: %s", method, path, exc)
                raise

    async def _send(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        content: bytes | None = None,
        params: dict[str, str] | None = None,
        auth: tuple[str, str] | None = None,
    ) -> dict:
        """One request, repeated after failures that pass; the PayPal-Request-Id keeps a repeated POST from acting
        twice."""
        url = self.api_base + path
        attempt = 0
        while True:
            try:
                response = await self._http.request(
                    method, url, content=content, headers=headers, params=params, auth=auth, timeout=self.timeout
                )
            except httpx.RequestError as exc:
                error = PayPalError(0, "NETWORK_ERROR", f"{type(exc).__name__} while calling PayPal {path}")
            else:
                if response.is_success:
                    return _body(response)
                error = _error(response)
            if not error.retryable or attempt >= self.retries:
                raise error
            attempt += 1
            await asyncio.sleep(self.backoff * 2 ** (attempt - 1))


def _resource(value: str) -> str:
    if not isinstance(value, str) or not RESOURCE_ID.match(value):
        raise ValueError(f"Not a PayPal ID: {value!r}")
    return value


def _body(response: httpx.Response) -> dict:
    if not response.content:
        return {}
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _error(response: httpx.Response) -> PayPalError:
    """PayPal's error answer: name, message, debug_id, details and links, or OAuth's error and error_description."""
    data = _body(response)
    details = [detail for detail in data.get("details") or [] if isinstance(detail, dict)]
    links = [link for link in data.get("links") or [] if isinstance(link, dict)]
    return PayPalError(
        response.status_code,
        str(data.get("name") or data.get("error") or f"HTTP_{response.status_code}"),
        str(data.get("message") or data.get("error_description") or response.reason_phrase or "No message"),
        data.get("debug_id") or response.headers.get("paypal-debug-id"),
        details,
        links,
    )


# Money, time and idempotency keys


def decimal_amount(value: object) -> Decimal:
    """Money as a Decimal, from a string, a Decimal or an int. Floats are refused: they cannot hold cents exactly."""
    if isinstance(value, bool) or not isinstance(value, str | Decimal | int):
        raise TypeError(f"Money is a string or a Decimal, not {type(value).__name__}")
    try:
        return Decimal(value.strip() if isinstance(value, str) else value)
    except InvalidOperation as exc:
        raise ValueError(f"{value!r} is not an amount") from exc


def money(value: str | Decimal | int, currency: str) -> str:
    """An amount as PayPal writes it: '19.00', or whole units for JPY, HUF and TWD. It must be positive and have no
    more decimals than the currency."""
    amount = decimal_amount(value)
    places = 0 if currency.upper() in ZERO_DECIMAL else 2
    if not amount.is_finite() or amount <= 0:
        raise ValueError(f"{value!r} is not a positive amount")
    exact = amount.quantize(Decimal(1).scaleb(-places))
    if exact != amount:
        raise ValueError(f"{value!r} has more decimals than {currency.upper()} allows")
    return str(exact)


def money_object(amount: str | Decimal | int, currency: str | None) -> dict:
    if not currency:
        raise ValueError("An amount needs its currency.")
    code = currency.upper()
    return {"currency_code": code, "value": money(amount, code)}


def parse_time(value: object) -> datetime | None:
    """A PayPal timestamp ('2026-10-22T14:03:00Z' or '2026-10-22T07:03:00-07:00') in UTC; None when absent or bad."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).astimezone(UTC)


def format_time(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def request_key(*parts: str) -> str:
    """A PayPal-Request-Id that is the same every time for the same operation on the same resource, so a repeated
    settlement gets PayPal's earlier answer instead of acting twice."""
    return str(uuid.uuid5(REQUEST_KEYS, "|".join(parts)))


# Reading PayPal's answers


def _units(order: Mapping[str, Any]) -> list[dict]:
    return [unit for unit in order.get("purchase_units") or [] if isinstance(unit, dict)]


def _payments(order: Mapping[str, Any], kind: str) -> list[dict]:
    """The order's captures or authorizations, across its purchase units."""
    return [
        payment
        for unit in _units(order)
        for payment in (unit.get("payments") or {}).get(kind) or []
        if isinstance(payment, dict)
    ]


def payer_id(order: Mapping[str, Any]) -> str | None:
    payer = order.get("payer") or {}
    wallet = (order.get("payment_source") or {}).get("paypal") or {}
    return payer.get("payer_id") or wallet.get("account_id")


def approval_url(order: Mapping[str, Any]) -> str | None:
    """Where the buyer approves an order: its payer-action link, or approve for orders made without a payment source."""
    links = {link.get("rel"): link.get("href") for link in order.get("links") or [] if isinstance(link, dict)}
    return links.get("payer-action") or links.get("approve")


def summarize_capture(order: Mapping[str, Any]) -> dict:
    """A paid order's facts: the order's status, its (first) capture's ID, status and amount, the payer and our
    custom_id."""
    units = _units(order)
    unit = units[0] if units else {}
    captures = _payments(order, "captures")
    capture = captures[0] if captures else {}
    amount = capture.get("amount") or unit.get("amount") or {}
    return {
        "order_id": order.get("id"),
        "status": order.get("status"),
        "capture_id": capture.get("id"),
        "capture_status": capture.get("status"),
        "amount": amount.get("value"),
        "currency": amount.get("currency_code"),
        "payer_id": payer_id(order),
        "custom_id": capture.get("custom_id") or unit.get("custom_id"),
    }


def paid_in_full(order: Mapping[str, Any], expected_amount: str | Decimal, currency: str, custom_id: str) -> bool:
    """Whether an order was paid exactly as sold: completed, with one completed capture of exactly the expected amount
    and currency, for our custom_id. Pending, refunded and partial payments do not count."""
    expected = decimal_amount(expected_amount)
    if order.get("status") != "COMPLETED" or len(_payments(order, "captures")) != 1:
        return False
    summary = summarize_capture(order)
    return (
        summary["capture_status"] == "COMPLETED"
        and _same_money(summary, expected, currency)
        and summary["custom_id"] == custom_id
    )


def capture_from(order: Mapping[str, Any], authorization_ids: Iterable[str]) -> str | None:
    """The ID of the order's capture made from one of these authorizations (its 'up' link points there), else of the
    order's only capture."""
    wanted = set(authorization_ids)
    captures = _payments(order, "captures")
    for capture in captures:
        for link in capture.get("links") or []:
            up = isinstance(link, dict) and link.get("rel") == "up"
            if up and str(link.get("href") or "").rstrip("/").rsplit("/", 1)[-1] in wanted:
                return capture.get("id")
    return captures[0].get("id") if len(captures) == 1 else None


def summarize_authorization(order: Mapping[str, Any]) -> dict:
    """A held order's facts: the order's status, its (first) authorization's ID, status, amount and expiry, the end
    of its honor period (created + 3 days), the payer and our custom_id. Times are ISO 8601 in UTC."""
    units = _units(order)
    unit = units[0] if units else {}
    authorizations = _payments(order, "authorizations")
    authorization = authorizations[0] if authorizations else {}
    amount = authorization.get("amount") or unit.get("amount") or {}
    created = parse_time(authorization.get("create_time"))
    expires = parse_time(authorization.get("expiration_time"))
    if created is None and expires is not None:  # some answers leave out create_time; the hold lasts 29 days from it
        created = expires - AUTHORIZATION_PERIOD
    if expires is None and created is not None:
        expires = created + AUTHORIZATION_PERIOD
    return {
        "order_id": order.get("id"),
        "status": order.get("status"),
        "authorization_id": authorization.get("id"),
        "authorization_status": authorization.get("status"),
        "amount": amount.get("value"),
        "currency": amount.get("currency_code"),
        "created_at": format_time(created) if created else None,
        "expiration_time": format_time(expires) if expires else None,
        "honor_period_end": format_time(created + HONOR_PERIOD) if created else None,
        "payer_id": payer_id(order),
        "custom_id": authorization.get("custom_id") or unit.get("custom_id"),
    }


def authorized_in_full(order: Mapping[str, Any], expected_amount: str | Decimal, currency: str, custom_id: str) -> bool:
    """Whether an order holds exactly the pledged money: completed, with one live (CREATED) authorization of exactly
    the expected amount and currency, for our custom_id."""
    expected = decimal_amount(expected_amount)
    if order.get("status") != "COMPLETED" or len(_payments(order, "authorizations")) != 1:
        return False
    summary = summarize_authorization(order)
    return (
        summary["authorization_status"] == "CREATED"
        and _same_money(summary, expected, currency)
        and summary["custom_id"] == custom_id
    )


def _same_money(summary: dict, expected: Decimal, currency: str) -> bool:
    try:
        amount = decimal_amount(summary["amount"])
    except (TypeError, ValueError):
        return False
    return amount == expected and str(summary["currency"] or "").upper() == currency.upper()


def net_amount(capture: Mapping[str, Any]) -> tuple[str, str] | None:
    """What the seller receives from a capture after PayPal's fee (its seller_receivable_breakdown's net_amount), as
    (value, currency); None while the capture is pending, when PayPal does not give the breakdown yet."""
    breakdown = capture.get("seller_receivable_breakdown")
    net = breakdown.get("net_amount") if isinstance(breakdown, Mapping) else None
    if not isinstance(net, Mapping):
        return None
    value, currency = net.get("value"), net.get("currency_code")
    try:
        amount = decimal_amount(value)
    except (TypeError, ValueError):
        return None
    if not isinstance(currency, str) or not amount.is_finite() or amount < 0:
        return None
    return str(amount), currency.upper()


def summarize_payout(answer: Mapping[str, Any]) -> dict:
    """A payout batch's facts, from create_payout's answer, get_payout_batch's or a payout webhook's resource (a batch,
    or one of its items): the batch's id and status, its (first) item's id and status, the receiver, our
    sender_batch_id, and the payout as the owner sees it: "pending", "paid" or "failed"."""
    header = answer.get("batch_header") if isinstance(answer.get("batch_header"), Mapping) else {}
    items = [item for item in answer.get("items") or [] if isinstance(item, Mapping)]
    item: Mapping[str, Any] = items[0] if items else {}
    if not header and answer.get("payout_item_id"):  # a payout item on its own, as its webhooks carry it
        item = answer
    detail = item.get("payout_item") if isinstance(item.get("payout_item"), Mapping) else {}
    sender = header.get("sender_batch_header") if isinstance(header.get("sender_batch_header"), Mapping) else {}
    batch_status = header.get("batch_status")
    item_status = item.get("transaction_status")
    errors = item.get("errors") if isinstance(item.get("errors"), Mapping) else {}
    if isinstance(item_status, str) and item_status in PAYOUT_ITEM_STATUS:
        status = PAYOUT_ITEM_STATUS[item_status]
    else:
        status = PAYOUT_BATCH_STATUS.get(batch_status or "", "pending")
    return {
        "payout_batch_id": header.get("payout_batch_id") or item.get("payout_batch_id"),
        "batch_status": batch_status,
        "payout_item_id": item.get("payout_item_id"),
        "item_status": item_status,
        "sender_batch_id": sender.get("sender_batch_id") or item.get("sender_batch_id"),
        "receiver": detail.get("receiver"),
        "status": status,
        "error": errors.get("name") if isinstance(errors.get("name"), str) else None,
    }


def duplicate_payout(exc: PayPalError) -> str | None:
    """The batch id of the payout PayPal already made with this sender_batch_id, when that is why it refused a payout:
    its error links to the original batch, at the error's top level as PayPal's reference shows, or in the detail about
    SENDER_BATCH_ID (`details[].link`) as the sandbox sends it."""
    if exc.status not in (400, 409, 422):
        return None
    text = " ".join([exc.name, exc.message, *(str(detail.get("issue") or "") for detail in exc.details)]).lower()
    if "sender_batch_id" not in text and "duplicate" not in text and "already exists" not in text:
        return None
    links = list(exc.links)
    for detail in exc.details:
        for key in ("link", "links"):
            found = detail.get(key)
            if isinstance(found, list):
                links.extend(link for link in found if isinstance(link, Mapping))
    for link in links:
        href = str(link.get("href") or "").rstrip("/")
        if "/v1/payments/payouts/" in href:
            found = href.rsplit("/", 1)[-1].split("?", 1)[0]
            if RESOURCE_ID.match(found):
                return found
    return None
