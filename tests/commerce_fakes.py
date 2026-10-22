"""Fakes for the paid features' tests: PayPal's sandbox in memory (an httpx.MockTransport handler), the payment
settings, and an app wired to them with the settlement loop off. Accounts' fakes come from tests.account_fakes."""
from __future__ import annotations

import itertools
import json
import re
import time
from datetime import UTC, datetime, timedelta

import httpx
from fastapi.testclient import TestClient

from app.payments.paypal import PayPalClient
from tests import account_fakes
from tests.account_fakes import Clock, GoogleSigner, dev_sign_in, run_survey

__all__ = [
    "API", "CRON_SECRET", "WEBHOOK_ID", "Clock", "FakePayPal", "GoogleSigner", "buy_kit", "configure", "dev_sign_in",
    "make_client", "run_survey", "wait_for_kit", "webhook",
]

API = "https://api-m.sandbox.paypal.com"
CRON_SECRET = "a-long-cron-secret"
WEBHOOK_ID = "WH-TEST-1"
PAYMENT_SETTINGS = {
    "cron_secret": CRON_SECRET, "kit_refund_days": 14, "kit_price": "19.00", "kit_currency": "USD",
    "paypal_client_id": "test-paypal-client", "paypal_client_secret": "test-paypal-secret", "paypal_env": "sandbox",
    "paypal_webhook_id": WEBHOOK_ID,
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


def failure(status: int, name: str, issue: str | None = None) -> httpx.Response:
    body: dict = {"name": name, "message": "The requested action could not be performed.", "debug_id": "dbg123"}
    if issue:
        body["details"] = [{"issue": issue, "description": issue}]
    return httpx.Response(status, json=body)


class FakePayPal:
    """PayPal's sandbox in memory. Buyers approve every order at once; knobs make PayPal decline, leave captures
    pending, fail for a while or refuse a webhook. Every request is recorded."""

    def __init__(self, clock: Clock | None = None) -> None:
        self.clock = clock or Clock()
        self.requests: list[httpx.Request] = []
        self.orders: dict[str, dict] = {}
        self.authorizations: dict[str, dict] = {}  # id -> {"status", "order_id"}
        self.captures: dict[str, dict] = {}  # id -> {"status", "order_id", "refunded"}
        self.decline: list[str] = []  # order ids whose next capture or authorization the card declines
        self.capture_status = "COMPLETED"  # of kit captures: PENDING while PayPal reviews them
        self.unavailable: dict[str, int] = {}  # authorization id -> captures or renewals that fail with 503 first
        self.refuse: dict[str, str] = {}  # authorization id -> the issue its capture is refused with
        self.webhook_genuine = True
        self.payers = (f"PAYER{n}" for n in itertools.count(1))
        self.ids = itertools.count(1)
        self._answers: dict[tuple[str, str], tuple[int, bytes]] = {}

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
            return httpx.Response(200, json={"verification_status": "SUCCESS" if self.webhook_genuine else "FAILURE"})
        found = re.fullmatch(r"/v2/checkout/orders/([^/]+)(?:/(capture|authorize))?", path)
        if found:
            order = self.orders.get(found.group(1))
            if order is None:
                return failure(404, "RESOURCE_NOT_FOUND", "INVALID_RESOURCE_ID")
            if found.group(2) == "capture":
                return self._capture_order(order)
            if found.group(2) == "authorize":
                return self._authorize_order(order)
            return httpx.Response(200, json=order)
        found = re.fullmatch(r"/v2/payments/authorizations/([^/]+)/(capture|void|reauthorize)", path)
        if found:
            return self._authorization(found.group(1), found.group(2))
        found = re.fullmatch(r"/v2/payments/captures/([^/]+)/refund", path)
        if found:
            capture = self.captures.get(found.group(1))
            if capture is None:
                return failure(404, "RESOURCE_NOT_FOUND", "INVALID_RESOURCE_ID")
            if capture["refunded"]:
                return failure(422, "UNPROCESSABLE_ENTITY", "CAPTURE_FULLY_REFUNDED")
            capture["refunded"] = True
            return httpx.Response(201, json={"id": f"REFUND{next(self.ids)}", "status": "COMPLETED"})
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

    def _approve(self, order: dict) -> None:
        if "payer" not in order:
            order["payer"] = {"payer_id": next(self.payers), "email_address": "buyer@example.com"}

    def _capture_order(self, order: dict) -> httpx.Response:
        if order["id"] in self.decline:
            self.decline.remove(order["id"])
            return failure(422, "UNPROCESSABLE_ENTITY", "INSTRUMENT_DECLINED")
        if order["status"] == "COMPLETED":
            return failure(422, "UNPROCESSABLE_ENTITY", "ORDER_ALREADY_CAPTURED")
        self._approve(order)
        unit = order["purchase_units"][0]
        capture_id = f"CAPTURE{next(self.ids)}"
        self.captures[capture_id] = {"status": self.capture_status, "order_id": order["id"], "refunded": False}
        unit["payments"] = {"captures": [{
            "id": capture_id, "status": self.capture_status, "amount": unit["amount"], "custom_id": unit["custom_id"],
            "final_capture": True, "create_time": paypal_time(self.clock()),
        }]}
        order["status"] = "COMPLETED"
        return httpx.Response(201, json=order)

    def complete_capture(self, order_id: str) -> dict:
        """PayPal finishes reviewing a pending capture; the capture resource a webhook would carry."""
        capture = self.orders[order_id]["purchase_units"][0]["payments"]["captures"][0]
        capture["status"] = "COMPLETED"
        self.captures[capture["id"]]["status"] = "COMPLETED"
        return {**capture, "supplementary_data": {"related_ids": {"order_id": order_id}}}

    def _authorize_order(self, order: dict) -> httpx.Response:
        if order["id"] in self.decline:
            self.decline.remove(order["id"])
            return failure(422, "UNPROCESSABLE_ENTITY", "INSTRUMENT_DECLINED")
        if order["status"] == "COMPLETED":
            return failure(422, "UNPROCESSABLE_ENTITY", "ORDER_ALREADY_AUTHORIZED")
        self._approve(order)
        unit = order["purchase_units"][0]
        authorization_id = f"AUTH{next(self.ids)}"
        now = self.clock()
        self.authorizations[authorization_id] = {"status": "CREATED", "order_id": order["id"]}
        unit["payments"] = {"authorizations": [{
            "id": authorization_id, "status": "CREATED", "amount": unit["amount"], "custom_id": unit["custom_id"],
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
            self.authorizations[renewed] = {"status": "CREATED", "order_id": held["order_id"]}
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
        capture_id = f"CAPTURE{next(self.ids)}"
        self.captures[capture_id] = {"status": "COMPLETED", "order_id": held["order_id"], "refunded": False}
        return httpx.Response(201, json={
            "id": capture_id, "status": "COMPLETED",
            "links": [{"rel": "up", "href": f"{API}/v2/payments/authorizations/{authorization_id}"}],
        })


def make_client(paypal: FakePayPal | None = None, **options) -> TestClient:
    """The accounts' test app (tests.account_fakes.make_client) with this PayPal and no settlement loop (tests run
    app.state.settler.run_once)."""
    return account_fakes.make_client(services={"paypal": paypal.client() if paypal else None}, settle_every=None, **options)


def wait_for_kit(client: TestClient, token: str, timeout: float = 30.0) -> dict:
    """The kit's page once its build has ended."""
    deadline = time.monotonic() + timeout
    while True:
        page = client.get(f"/api/kits/{token}").json()
        if page["status"] != "building" or time.monotonic() > deadline:
            return page
        time.sleep(0.05)


def buy_kit(client: TestClient, run_id: str, index: int = 0) -> dict:
    """Checkout, approval (the fake buyer approves at once) and capture; the kit's page once built."""
    order_id = client.post("/api/checkout", json={"run_id": run_id, "index": index}).json()["order_id"]
    captured = client.post(f"/api/checkout/{order_id}/capture")
    assert captured.status_code == 200, captured.text
    page = wait_for_kit(client, captured.json()["token"])
    assert page["status"] == "ready", page
    return page


def webhook(client: TestClient, event_id: str, kind: str, resource: dict) -> httpx.Response:
    """A webhook delivery from PayPal, as raw JSON with its signature headers."""
    body = json.dumps({"id": event_id, "event_type": kind, "resource": resource})
    return client.post("/api/paypal/webhook", content=body, headers={**WEBHOOK_HEADERS, "content-type": "application/json"})
