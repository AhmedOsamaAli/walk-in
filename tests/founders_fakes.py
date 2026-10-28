"""Fakes for Walk-in Founders' tests: PayPal's sandbox in memory (an httpx.MockTransport handler) with Orders, Payments,
Payouts and webhook verification, the payment settings, an app wired to them with the settlement loop off, and two
requests raced around a PayPal call. Accounts' fakes come from tests.account_fakes."""
from __future__ import annotations

import asyncio
import itertools
import json
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
from fastapi.testclient import TestClient

from app.payments.paypal import PayPalClient
from tests import account_fakes
from tests.account_fakes import Clock, dev_sign_in, run_survey

__all__ = [
    "API", "CRON_SECRET", "WEBHOOK_HEADERS", "WEBHOOK_ID", "Clock", "FakePayPal", "configure", "dev_sign_in",
    "make_client", "race", "ready_kit", "run_survey", "wait_for_kit", "webhook",
]

API = "https://api-m.sandbox.paypal.com"
CRON_SECRET = "a-long-cron-secret"
WEBHOOK_ID = "WH-TEST-1"
PAYMENT_SETTINGS = {
    "cron_secret": CRON_SECRET, "paypal_client_id": "test-paypal-client", "paypal_client_secret": "test-paypal-secret",
    "paypal_env": "sandbox", "paypal_webhook_id": WEBHOOK_ID, "surveys_paused": False,
}
# The headers PayPal signs a webhook delivery with; the fake PayPal confirms them (or not, with webhook_genuine).
WEBHOOK_HEADERS = {
    "paypal-auth-algo": "SHA256withRSA", "paypal-cert-url": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT",
    "paypal-transmission-id": "69cd13f0-d67a-11e5-baa3-778b53f4ae55", "paypal-transmission-sig": "c2lnbmF0dXJl",
    "paypal-transmission-time": "2026-10-22T14:03:00Z",
}


def configure(monkeypatch, **changes):
    """The accounts' test settings and the payment ones, for every app module."""
    return account_fakes.configure(monkeypatch, **{**PAYMENT_SETTINGS, **changes})


def paypal_time(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def failure(status: int, name: str, issue: str | None = None, **extra) -> httpx.Response:
    body: dict = {"name": name, "message": "The requested action could not be performed.", "debug_id": "dbg123", **extra}
    if issue:
        body["details"] = [{"issue": issue, "description": issue}]
    return httpx.Response(status, json=body)


def fee(gross: str) -> Decimal:
    """PayPal's fee in the fake: 3.49% plus 49 cents, to the cent."""
    return (Decimal(gross) * Decimal("0.0349") + Decimal("0.49")).quantize(Decimal("0.01"))


class FakePayPal:
    """PayPal's sandbox in memory. Buyers approve every order at once, unless it is in `unapproved`; knobs make PayPal
    decline a payment method, deny a hold, leave captures pending, fail for a while, refuse a capture, a payout or a
    webhook. Every request is recorded, and a repeated POST with the same PayPal-Request-Id gets the first answer."""

    def __init__(self, clock: Clock | None = None) -> None:
        self.clock = clock or Clock()
        self.requests: list[httpx.Request] = []
        self.orders: dict[str, dict] = {}
        self.authorizations: dict[str, dict] = {}  # id -> {"status", "order_id", "amount", "custom_id"}
        self.captures: dict[str, dict] = {}  # id -> the capture resource
        self.payouts: dict[str, dict] = {}  # payout_batch_id -> the batch
        self.decline: list[str] = []  # order ids whose next authorization the card declines (INSTRUMENT_DECLINED)
        self.deny: list[str] = []  # order ids whose hold PayPal places DENIED
        self.unapproved: set[str] = set()  # order ids the buyer has not approved yet
        self.capture_status = "COMPLETED"  # PENDING: captures wait for PayPal's review
        self.unavailable: dict[str, int] = {}  # authorization id -> captures or renewals that fail with 503 first
        self.refuse: dict[str, str] = {}  # authorization id -> the issue its capture is refused with
        self.payout_refusal: str | None = None  # the issue every payout is refused with
        self.payout_outage = 0  # payouts that fail with 503 first
        self.webhook_genuine = True
        self.verify_outage = False  # PayPal cannot confirm webhook signatures for now
        self.payers = (f"PAYER{n}" for n in itertools.count(1))
        self.ids = itertools.count(1)
        self._answers: dict[tuple[str, str], tuple[int, bytes]] = {}
        self._batches: dict[str, str] = {}  # sender_batch_id -> payout_batch_id

    def client(self) -> PayPalClient:
        return PayPalClient("test-paypal-client", "test-paypal-secret", API,
                            http_client=httpx.AsyncClient(transport=httpx.MockTransport(self)), backoff=0)

    def calls(self, pattern: str, method: str = "POST") -> list[httpx.Request]:
        return [r for r in self.requests if r.method == method and re.fullmatch(pattern, r.url.path)]

    def body(self, request: httpx.Request) -> dict:
        return json.loads(request.content) if request.content else {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "token", "token_type": "Bearer", "expires_in": 32400})
        key = (path, request.headers.get("paypal-request-id", ""))
        if request.method == "POST" and key in self._answers:  # PayPal answers a repeated request as it did before
            status, content = self._answers[key]
            return httpx.Response(status, content=content, headers={"content-type": "application/json"})
        answer = self._answer(request, path)
        if request.method == "POST" and answer.status_code < 500 and key[1]:
            self._answers[key] = (answer.status_code, answer.content)
        return answer

    def _answer(self, request: httpx.Request, path: str) -> httpx.Response:
        if path == "/v2/checkout/orders":
            return self._create(self.body(request))
        if path == "/v1/notifications/verify-webhook-signature":
            if self.verify_outage:
                return failure(503, "SERVICE_UNAVAILABLE")
            return httpx.Response(200, json={"verification_status": "SUCCESS" if self.webhook_genuine else "FAILURE"})
        if path == "/v1/payments/payouts" and request.method == "POST":
            return self._payout(self.body(request))
        found = re.fullmatch(r"/v1/payments/payouts/([^/]+)", path)
        if found:
            batch = self.payouts.get(found.group(1))
            return httpx.Response(200, json=batch) if batch else failure(404, "RESOURCE_NOT_FOUND", "INVALID_RESOURCE_ID")
        found = re.fullmatch(r"/v2/checkout/orders/([^/]+)(?:/(authorize|capture))?", path)
        if found:
            order = self.orders.get(found.group(1))
            if order is None:
                return failure(404, "RESOURCE_NOT_FOUND", "INVALID_RESOURCE_ID")
            if found.group(2) == "authorize":
                return self._authorize_order(order)
            if found.group(2) == "capture":
                return failure(422, "UNPROCESSABLE_ENTITY", "ACTION_DOES_NOT_MATCH_INTENT")
            return httpx.Response(200, json=order)
        found = re.fullmatch(r"/v2/payments/authorizations/([^/]+)/(capture|void|reauthorize)", path)
        if found:
            return self._authorization(found.group(1), found.group(2))
        found = re.fullmatch(r"/v2/payments/captures/([^/]+)", path)
        if found:
            capture = self.captures.get(found.group(1))
            return httpx.Response(200, json=capture) if capture else failure(404, "RESOURCE_NOT_FOUND", "INVALID_RESOURCE_ID")
        return failure(404, "NOT_FOUND")

    def _create(self, body: dict) -> httpx.Response:
        order_id = f"ORDER{next(self.ids)}"
        unit = body["purchase_units"][0]
        self.orders[order_id] = {
            "id": order_id, "intent": body["intent"], "status": "PAYER_ACTION_REQUIRED",
            "purchase_units": [{**unit, "reference_id": unit.get("reference_id", "default")}],
            "links": [{"href": f"https://www.sandbox.paypal.com/checkoutnow?token={order_id}", "rel": "payer-action"}],
            "request": body,
        }
        return httpx.Response(200, json=self.orders[order_id])

    def _authorize_order(self, order: dict) -> httpx.Response:
        if order["id"] in self.unapproved:
            return failure(422, "UNPROCESSABLE_ENTITY", "ORDER_NOT_APPROVED")
        if order["id"] in self.decline:
            self.decline.remove(order["id"])
            return failure(422, "UNPROCESSABLE_ENTITY", "INSTRUMENT_DECLINED")
        if order["status"] == "COMPLETED":
            return failure(422, "UNPROCESSABLE_ENTITY", "ORDER_ALREADY_AUTHORIZED")
        if "payer" not in order:
            order["payer"] = {"payer_id": next(self.payers), "email_address": "buyer@example.com"}
        unit = order["purchase_units"][0]
        authorization_id = f"AUTH{next(self.ids)}"
        now = self.clock()
        status = "DENIED" if order["id"] in self.deny else "CREATED"
        self.authorizations[authorization_id] = {
            "status": status, "order_id": order["id"], "amount": unit["amount"], "custom_id": unit["custom_id"],
        }
        unit["payments"] = {"authorizations": [{
            "id": authorization_id, "status": status, "amount": unit["amount"], "custom_id": unit["custom_id"],
            "create_time": paypal_time(now), "expiration_time": paypal_time(now + timedelta(days=29)),
        }]}
        order["status"] = "COMPLETED"
        return httpx.Response(201, json=order)

    def _authorization(self, authorization_id: str, action: str) -> httpx.Response:
        held = self.authorizations.get(authorization_id)
        if held is None:
            return failure(404, "RESOURCE_NOT_FOUND", "INVALID_RESOURCE_ID")
        if action != "void" and self.unavailable.get(authorization_id):
            self.unavailable[authorization_id] -= 1
            return failure(503, "SERVICE_UNAVAILABLE")
        if action == "reauthorize":
            renewed = f"REAUTH{next(self.ids)}"
            self.authorizations[renewed] = {**held, "status": "CREATED", "renews": authorization_id}
            if authorization_id in self.refuse:  # the renewed hold is the same payment method's
                self.refuse[renewed] = self.refuse[authorization_id]
            return httpx.Response(201, json={"id": renewed, "status": "CREATED"})
        if held["status"] == "VOIDED":
            return failure(422, "UNPROCESSABLE_ENTITY", "AUTHORIZATION_VOIDED")
        if held["status"] == "CAPTURED":
            return failure(422, "UNPROCESSABLE_ENTITY", "AUTHORIZATION_ALREADY_CAPTURED")
        if action == "void":
            held["status"] = "VOIDED"
            return httpx.Response(204)
        if authorization_id in self.refuse:
            return failure(422, "UNPROCESSABLE_ENTITY", self.refuse[authorization_id])
        held["status"] = "CAPTURED"
        original = self.authorizations.get(held.get("renews", ""))
        if original:
            original["status"] = "CAPTURED"
        capture_id = f"CAPTURE{next(self.ids)}"
        gross = held["amount"]["value"]
        capture = {
            "id": capture_id, "status": self.capture_status, "amount": held["amount"], "custom_id": held["custom_id"],
            "final_capture": True, "create_time": paypal_time(self.clock()),
            "links": [{"rel": "up", "href": f"{API}/v2/payments/authorizations/{authorization_id}"}],
            "supplementary_data": {"related_ids": {"order_id": held["order_id"], "authorization_id": authorization_id}},
        }
        if self.capture_status == "COMPLETED":
            capture["seller_receivable_breakdown"] = self.breakdown(gross)
        self.captures[capture_id] = capture
        return httpx.Response(201, json=capture)

    @staticmethod
    def breakdown(gross: str) -> dict:
        charged = fee(gross)
        return {
            "gross_amount": {"currency_code": "USD", "value": gross},
            "paypal_fee": {"currency_code": "USD", "value": str(charged)},
            "net_amount": {"currency_code": "USD", "value": str(Decimal(gross) - charged)},
        }

    def complete_capture(self, capture_id: str) -> dict:
        """PayPal finishes reviewing a pending capture; the capture resource a webhook would carry."""
        capture = self.captures[capture_id]
        capture["status"] = "COMPLETED"
        capture["seller_receivable_breakdown"] = self.breakdown(capture["amount"]["value"])
        return capture

    def _payout(self, body: dict) -> httpx.Response:
        header = body["sender_batch_header"]
        sender = header["sender_batch_id"]
        if self.payout_outage:
            self.payout_outage -= 1
            return failure(503, "SERVICE_UNAVAILABLE")
        if self.payout_refusal:
            return failure(422, "UNPROCESSABLE_ENTITY", self.payout_refusal)
        if sender in self._batches:  # PayPal pays a sender_batch_id once in 30 days
            original = self._batches[sender]
            # As the sandbox answers (Oct 2026): the link to the original batch sits in the detail, not at the top.
            return httpx.Response(400, json={
                "name": "USER_BUSINESS_ERROR", "message": "User business error.", "debug_id": "dbg123",
                "details": [{"field": "SENDER_BATCH_ID", "location": "body",
                             "issue": "Batch with given sender_batch_id already exists",
                             "link": [{"href": f"{API}/v1/payments/payouts/{original}", "rel": "self", "method": "GET",
                                       "encType": "application/json"}]}],
            })
        batch_id = f"BATCH{next(self.ids)}"
        item = body["items"][0]
        self._batches[sender] = batch_id
        self.payouts[batch_id] = {
            "batch_header": {"payout_batch_id": batch_id, "batch_status": "PENDING",
                             "sender_batch_header": {**header}},
            "items": [{"payout_item_id": f"ITEM{next(self.ids)}", "transaction_status": "PENDING",
                       "payout_batch_id": batch_id, "payout_item": item}],
        }
        return httpx.Response(201, json={"batch_header": self.payouts[batch_id]["batch_header"]})

    def finish_payout(self, batch_id: str, status: str = "SUCCESS") -> dict:
        """PayPal pays (or fails) a payout's item; the item resource its webhook carries."""
        batch = self.payouts[batch_id]
        item = batch["items"][0]
        item["transaction_status"] = status
        batch["batch_header"]["batch_status"] = "SUCCESS"
        if status != "SUCCESS":
            item["errors"] = {"name": "RECEIVER_UNREGISTERED", "message": "The receiver has no PayPal account."}
        return {**item, "sender_batch_id": batch["batch_header"]["sender_batch_header"]["sender_batch_id"]}


def make_client(paypal: FakePayPal | None = None, **options) -> TestClient:
    """The accounts' test app (tests.account_fakes.make_client) with this PayPal and no settlement loop (tests run
    app.state.settler.run_once)."""
    options.setdefault("settle_every", None)
    return account_fakes.make_client(services={"paypal": paypal.client() if paypal else None}, **options)


def wait_for_kit(client: TestClient, token: str, timeout: float = 30.0) -> dict:
    """The kit's page once its build has ended."""
    deadline = time.monotonic() + timeout
    while True:
        page = client.get(f"/api/kits/{token}").json()
        if page["status"] != "building" or time.monotonic() > deadline:
            return page
        time.sleep(0.05)


def ready_kit(client: TestClient, run_id: str, index: int = 0) -> dict:
    """The concept's launch kit (free), once built."""
    made = client.post("/api/kits", json={"run_id": run_id, "index": index})
    assert made.status_code == 200, made.text
    page = wait_for_kit(client, made.json()["token"])
    assert page["status"] == "ready", page
    return page


def webhook(client: TestClient, event_id: str, kind: str, resource: dict, headers: dict | None = None) -> httpx.Response:
    """A webhook delivery from PayPal, as raw JSON with its signature headers."""
    body = json.dumps({"id": event_id, "event_type": kind, "resource": resource})
    return client.post("/api/paypal/webhook", content=body,
                       headers={**WEBHOOK_HEADERS, "content-type": "application/json", **(headers or {})})


RACE_WAIT_S = 10.0


class WatchedLock(asyncio.Lock):
    """The settlement lock, noting when a request has to wait for it."""

    def __init__(self) -> None:
        super().__init__()
        self.waited = asyncio.Event()

    async def acquire(self) -> bool:
        if self.locked():
            self.waited.set()
        return await super().acquire()


def race(
    client: TestClient, first: tuple, then: tuple, *, paused: str, meanwhile: Callable[[], object] | None = None,
) -> tuple[httpx.Response, httpx.Response]:
    """Two requests that overlap, each a (method, path) or (method, path, headers): `first` is sent, and while PayPal
    holds up its first `paused` call (a PayPalClient method) `meanwhile` runs and `then` is sent. PayPal answers
    `first` once `then` has its answer or waits for the settlement lock, whichever comes first. Both answers."""
    state = client.app.state
    paypal = state.services.paypal
    real = getattr(paypal, paused)

    def send(http: httpx.AsyncClient, request: tuple) -> asyncio.Task:
        method, path, *headers = request
        return asyncio.create_task(http.request(method, path, headers=headers[0] if headers else None))

    async def run() -> tuple[httpx.Response, httpx.Response]:
        lock = state.settler.lock = WatchedLock()
        inside, go = asyncio.Event(), asyncio.Event()

        async def held_up(*args, **options):
            if not inside.is_set():
                inside.set()
                await go.wait()
            return await real(*args, **options)

        setattr(paypal, paused, held_up)
        try:
            transport = httpx.ASGITransport(app=client.app)
            async with httpx.AsyncClient(transport=transport, base_url=str(client.base_url), cookies=client.cookies) as http:
                one = send(http, first)
                await asyncio.wait_for(inside.wait(), RACE_WAIT_S)
                if meanwhile:
                    meanwhile()
                two = send(http, then)
                waited = asyncio.create_task(lock.waited.wait())
                await asyncio.wait({two, waited}, timeout=RACE_WAIT_S, return_when=asyncio.FIRST_COMPLETED)
                waited.cancel()
                go.set()
                return await asyncio.wait_for(one, RACE_WAIT_S), await asyncio.wait_for(two, RACE_WAIT_S)
        finally:
            delattr(paypal, paused)

    return client.portal.call(run)
