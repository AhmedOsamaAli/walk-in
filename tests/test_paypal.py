"""The PayPal REST client against a fake PayPal (httpx.MockTransport): tokens, request shapes, errors, readers."""
import asyncio
import base64
import json
import logging
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from app.payments import paypal
from app.payments.paypal import PayPalClient, PayPalError

API = "https://api-m.sandbox.paypal.com"


def token_reply(token: str = "token-1", expires_in: int = 32400) -> httpx.Response:
    return httpx.Response(200, json={
        "scope": "https://uri.paypal.com/services/payments/payment/authcapture", "access_token": token,
        "token_type": "Bearer", "app_id": "APP-80W284485P519543T", "expires_in": expires_in, "nonce": "n",
    })


def failure(status: int, name: str, issue: str | None = None, debug_id: str = "90bff07028f7f") -> httpx.Response:
    body = {"name": name, "message": "The requested action could not be performed.", "debug_id": debug_id}
    if issue:
        body["details"] = [{"issue": issue, "description": f"{issue} happened."}]
    return httpx.Response(status, json=body)


class Stub:
    """A fake PayPal: tokens from `tokens`, API answers from `replies` (then 200 {}), every request recorded."""

    def __init__(self, replies: list[httpx.Response] | None = None, tokens: list[str] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.replies = list(replies or [])
        self.tokens = list(tokens or ["token-1"])

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/v1/oauth2/token":
            return token_reply(self.tokens.pop(0) if len(self.tokens) > 1 else self.tokens[0])
        return self.replies.pop(0) if self.replies else httpx.Response(200, json={})

    def api(self) -> list[httpx.Request]:
        return [request for request in self.requests if request.url.path != "/v1/oauth2/token"]

    def token_requests(self) -> list[httpx.Request]:
        return [request for request in self.requests if request.url.path == "/v1/oauth2/token"]


def client_for(handler, client_id: str = "client-id", secret: str = "client-secret", **kwargs) -> PayPalClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return PayPalClient(client_id, secret, API, http_client=http, **kwargs)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_the_token_is_cached_and_renewed_shortly_before_it_expires():
    stub, clock = Stub(tokens=["token-1", "token-2"]), Clock()
    client = client_for(stub, clock=clock)

    async def run():
        await client.get_order("ORDER1")
        await client.get_order("ORDER1")
        clock.now += 32400 - 301  # still fresh: renewed 300 s before PayPal's expiry
        await client.get_order("ORDER1")
        clock.now += 2
        await client.get_order("ORDER1")

    asyncio.run(run())
    first = stub.token_requests()[0]
    assert len(stub.token_requests()) == 2
    assert first.method == "POST"
    assert first.headers["authorization"] == "Basic " + base64.b64encode(b"client-id:client-secret").decode()
    assert first.headers["content-type"] == "application/x-www-form-urlencoded"
    assert first.content == b"grant_type=client_credentials"
    assert [request.headers["authorization"] for request in stub.api()] == ["Bearer token-1"] * 3 + ["Bearer token-2"]


def test_concurrent_requests_wait_for_a_single_token_request():
    token_calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            token_calls.append(request)
            await asyncio.sleep(0.05)  # every request arrives while the token is on its way
            return token_reply()
        return httpx.Response(200, json={"id": request.url.path.rsplit("/", 1)[-1]})

    client = client_for(handler)

    async def run():
        return await asyncio.gather(*(client.get_order(f"ORDER{i}") for i in range(5)))

    orders = asyncio.run(run())
    assert len(token_calls) == 1
    assert [order["id"] for order in orders] == [f"ORDER{i}" for i in range(5)]


def test_a_token_paypal_no_longer_accepts_is_renewed_once():
    stub = Stub(replies=[failure(401, "AUTHENTICATION_FAILURE"), httpx.Response(200, json={"id": "ORDER1"})],
                tokens=["old", "new"])
    client = client_for(stub)
    assert asyncio.run(client.get_order("ORDER1")) == {"id": "ORDER1"}
    assert [request.headers["authorization"] for request in stub.api()] == ["Bearer old", "Bearer new"]

    always = Stub(replies=[failure(401, "AUTHENTICATION_FAILURE")] * 3, tokens=["a", "b", "c"])
    with pytest.raises(PayPalError) as error:
        asyncio.run(client_for(always).get_order("ORDER1"))
    assert error.value.status == 401 and len(always.api()) == 2  # one renewal, then the error


def test_a_kit_order_pays_now_without_shipping_and_carries_idempotency_headers():
    stub = Stub(replies=[httpx.Response(200, json={"id": "ORDER1", "status": "PAYER_ACTION_REQUIRED", "links": [
        {"href": f"{API}/v2/checkout/orders/ORDER1", "rel": "self", "method": "GET"},
        {"href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER1", "rel": "payer-action", "method": "GET"},
    ]})])
    order = asyncio.run(client_for(stub).create_order(
        intent="capture", amount="19", currency="usd", description="  Walk-in launch kit:\n Golden Hour ",
        custom_id="kit:run-1", request_id="kit-order-run-1",
    ))
    request = stub.api()[0]
    assert (request.method, request.url.path) == ("POST", "/v2/checkout/orders")
    assert request.headers["paypal-request-id"] == "kit-order-run-1"
    assert request.headers["prefer"] == "return=representation"
    assert request.headers["content-type"] == "application/json"
    assert json.loads(request.content) == {
        "intent": "CAPTURE",
        "purchase_units": [{
            "amount": {"currency_code": "USD", "value": "19.00"},
            "custom_id": "kit:run-1",
            "description": "Walk-in launch kit: Golden Hour",
        }],
        "payment_source": {"paypal": {"experience_context": {
            "brand_name": "Walk-in", "shipping_preference": "NO_SHIPPING", "user_action": "PAY_NOW",
            "payment_method_preference": "IMMEDIATE_PAYMENT_REQUIRED",
        }}},
    }
    assert paypal.approval_url(order) == "https://www.sandbox.paypal.com/checkoutnow?token=ORDER1"


def test_a_pledge_order_only_holds_the_money_and_returns_to_the_app():
    stub = Stub()
    asyncio.run(client_for(stub).create_order(
        intent="AUTHORIZE", amount=Decimal("25.5"), currency="USD", description="Pledge " + "x" * 200,
        custom_id="pledge:c1:p1", reference_id="c1", request_id="pledge-p1", brand_name="Walk-in: Golden Hour",
        return_url="https://walkin.example/pledge/done", cancel_url="https://walkin.example/pledge/cancel",
    ))
    body = json.loads(stub.api()[0].content)
    unit = body["purchase_units"][0]
    assert body["intent"] == "AUTHORIZE"
    assert unit["amount"] == {"currency_code": "USD", "value": "25.50"} and unit["reference_id"] == "c1"
    assert len(unit["description"]) == 127  # PayPal keeps 127 characters
    assert body["payment_source"]["paypal"]["experience_context"] == {
        "brand_name": "Walk-in: Golden Hour", "shipping_preference": "NO_SHIPPING", "user_action": "CONTINUE",
        "payment_method_preference": "IMMEDIATE_PAYMENT_REQUIRED",
        "return_url": "https://walkin.example/pledge/done", "cancel_url": "https://walkin.example/pledge/cancel",
    }


@pytest.mark.parametrize(("changes", "error"), [
    ({"amount": 19.0}, TypeError),
    ({"amount": "19.999"}, ValueError),
    ({"amount": "-1"}, ValueError),
    ({"amount": "NaN"}, ValueError),
    ({"intent": "SALE"}, ValueError),
    ({"custom_id": ""}, ValueError),
    ({"request_id": "x" * 109}, ValueError),
])
def test_bad_orders_never_reach_paypal(changes, error):
    stub = Stub()
    order = {"intent": "CAPTURE", "amount": "19.00", "currency": "USD", "description": "Kit", "custom_id": "kit:1",
             "request_id": "r1", **changes}
    with pytest.raises(error):
        asyncio.run(client_for(stub).create_order(**order))
    assert stub.api() == []


AMOUNT_25 = {"currency_code": "USD", "value": "25.00"}
CALLS = [
    ("get_order", ("ORDER1",), {}, "GET", "/v2/checkout/orders/ORDER1", None),
    ("capture_order", ("ORDER1", "r1"), {}, "POST", "/v2/checkout/orders/ORDER1/capture", {}),
    ("authorize_order", ("ORDER1", "r2"), {}, "POST", "/v2/checkout/orders/ORDER1/authorize", {}),
    ("capture_authorization", ("AUTH1", "r3"), {}, "POST", "/v2/payments/authorizations/AUTH1/capture",
     {"final_capture": True}),
    ("capture_authorization", ("AUTH1", "r4", "25"), {"final_capture": False, "currency": "usd"}, "POST",
     "/v2/payments/authorizations/AUTH1/capture", {"final_capture": False, "amount": AMOUNT_25}),
    ("void_authorization", ("AUTH1", "r5"), {}, "POST", "/v2/payments/authorizations/AUTH1/void", None),
    ("reauthorize_authorization", ("AUTH1", "r6", "25.00"), {"currency": "USD"}, "POST",
     "/v2/payments/authorizations/AUTH1/reauthorize", {"amount": AMOUNT_25}),
    ("reauthorize_authorization", ("AUTH1", "r7"), {}, "POST", "/v2/payments/authorizations/AUTH1/reauthorize", {}),
    ("get_authorization", ("AUTH1",), {}, "GET", "/v2/payments/authorizations/AUTH1", None),
    ("refund_capture", ("CAP1", "r8"), {}, "POST", "/v2/payments/captures/CAP1/refund", {}),
    ("refund_capture", ("CAP1", "r9", "25"), {"note": " The kit was  refunded ", "currency": "USD"}, "POST",
     "/v2/payments/captures/CAP1/refund", {"amount": AMOUNT_25, "note_to_payer": "The kit was refunded"}),
]


@pytest.mark.parametrize(("method", "args", "kwargs", "verb", "path", "body"), CALLS)
def test_every_call_sends_the_documented_request(method, args, kwargs, verb, path, body):
    stub = Stub(replies=[httpx.Response(201, json={"id": "X1", "status": "COMPLETED"})])
    answer = asyncio.run(getattr(client_for(stub), method)(*args, **kwargs))
    request = stub.api()[0]
    assert answer == {"id": "X1", "status": "COMPLETED"}
    assert (request.method, request.url.path) == (verb, path)
    assert request.headers["authorization"] == "Bearer token-1"
    if verb == "POST":
        assert request.headers["paypal-request-id"] == args[1]
        assert request.headers["prefer"] == "return=representation"
    else:
        assert "paypal-request-id" not in request.headers and "prefer" not in request.headers
    if body is None:
        assert request.content == b"" and "content-type" not in request.headers
    else:
        assert json.loads(request.content) == body and request.headers["content-type"] == "application/json"


def test_a_void_answered_with_no_content_reads_as_an_empty_answer():
    stub = Stub(replies=[httpx.Response(204)])
    assert asyncio.run(client_for(stub).void_authorization("AUTH1", "r1")) == {}


def test_amounts_need_their_currency_and_ids_must_be_paypal_ids():
    stub = Stub()
    client = client_for(stub)
    with pytest.raises(ValueError):
        asyncio.run(client.capture_authorization("AUTH1", "r1", "10.00"))
    for bad in ("../v1/oauth2/token", "ORDER 1", "", "ORDER1?x=1"):
        with pytest.raises(ValueError):
            asyncio.run(client.get_order(bad))
    assert stub.requests == []


def test_errors_carry_paypal_s_name_issues_and_debug_id():
    stub = Stub(replies=[failure(422, "UNPROCESSABLE_ENTITY", "INSTRUMENT_DECLINED")])
    with pytest.raises(PayPalError) as error:
        asyncio.run(client_for(stub).capture_order("ORDER1", "r1"))
    exc = error.value
    assert (exc.status, exc.name, exc.debug_id, exc.issues) == (422, "UNPROCESSABLE_ENTITY", "90bff07028f7f",
                                                                ["INSTRUMENT_DECLINED"])
    assert exc.details[0]["description"] == "INSTRUMENT_DECLINED happened."
    assert exc.has("INSTRUMENT_DECLINED") and exc.has("UNPROCESSABLE_ENTITY") and not exc.has("ORDER_NOT_APPROVED")
    assert not exc.retryable and len(stub.api()) == 1
    assert "INSTRUMENT_DECLINED" in str(exc) and "90bff07028f7f" in str(exc)


def test_failures_that_pass_are_retried_with_the_same_request_id():
    stub = Stub(replies=[
        failure(503, "SERVICE_UNAVAILABLE"),
        failure(409, "RESOURCE_CONFLICT", "PREVIOUS_REQUEST_IN_PROGRESS"),
        httpx.Response(201, json={"id": "CAP1", "status": "COMPLETED"}),
    ])
    capture = asyncio.run(client_for(stub, backoff=0).capture_authorization("AUTH1", "capture-auth1"))
    assert capture["id"] == "CAP1"
    assert [request.headers["paypal-request-id"] for request in stub.api()] == ["capture-auth1"] * 3

    exhausted = Stub(replies=[failure(500, "INTERNAL_SERVER_ERROR")] * 2)
    with pytest.raises(PayPalError) as error:
        asyncio.run(client_for(exhausted, backoff=0, retries=1).get_order("ORDER1"))
    assert error.value.status == 500 and error.value.retryable and len(exhausted.api()) == 2


def test_network_errors_become_paypal_errors():
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return token_reply()
        attempts.append(request)
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(PayPalError) as error:
        asyncio.run(client_for(handler, backoff=0, retries=1).get_order("ORDER1"))
    assert (error.value.status, error.value.name) == (0, "NETWORK_ERROR")
    assert error.value.retryable and len(attempts) == 2


def test_bad_credentials_map_oauth_s_error_and_missing_ones_send_nothing():
    stub = Stub()
    rejected = client_for(lambda request: httpx.Response(401, json={
        "error": "invalid_client", "error_description": "Client Authentication failed"}))
    with pytest.raises(PayPalError) as error:
        asyncio.run(rejected.get_order("ORDER1"))
    assert (error.value.status, error.value.name, error.value.message) == (401, "invalid_client",
                                                                           "Client Authentication failed")
    unconfigured = client_for(stub, client_id="", secret="")
    assert not unconfigured.configured
    with pytest.raises(PayPalError) as error:
        asyncio.run(unconfigured.get_order("ORDER1"))
    assert error.value.name == "NOT_CONFIGURED" and stub.requests == []


def test_secrets_and_tokens_never_reach_logs_errors_or_repr(caplog):
    caplog.set_level(logging.DEBUG)
    secret, token = "s3cret-client-secret", "A21AAF-very-secret-token"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return token_reply(token)
        return failure(500, "INTERNAL_SERVER_ERROR", debug_id="abc123")

    client = client_for(handler, secret=secret, retries=0)
    with pytest.raises(PayPalError) as error:
        asyncio.run(client.get_order("ORDER1"))
    basic = base64.b64encode(f"client-id:{secret}".encode()).decode()
    seen = caplog.text + str(error.value) + repr(error.value) + repr(client)
    assert "INTERNAL_SERVER_ERROR" in caplog.text and "abc123" in caplog.text  # the failure is logged
    assert secret not in seen and token not in seen and basic not in seen


def paid_order(capture: dict | None = None, **order: object) -> dict:
    """A captured kit order as PayPal returns it (Prefer: return=representation)."""
    paid = {
        "id": "CAP1", "status": "COMPLETED", "amount": {"currency_code": "USD", "value": "19.00"},
        "custom_id": "kit:run-1", "final_capture": True, "create_time": "2026-10-22T14:00:00Z",
    }
    return {
        "id": "ORDER1", "status": "COMPLETED", "intent": "CAPTURE",
        "payer": {"payer_id": "PAYER1", "email_address": "buyer@example.com"},
        "purchase_units": [{
            "reference_id": "default", "custom_id": "kit:run-1", "amount": {"currency_code": "USD", "value": "19.00"},
            "payments": {"captures": [{**paid, **(capture or {})}]},
        }],
        **order,
    }


def test_summarize_capture_reads_the_paid_order():
    assert paypal.summarize_capture(paid_order()) == {
        "order_id": "ORDER1", "status": "COMPLETED", "capture_id": "CAP1", "capture_status": "COMPLETED",
        "amount": "19.00", "currency": "USD", "payer_id": "PAYER1", "custom_id": "kit:run-1",
    }
    unpaid = paid_order(status="APPROVED")
    unpaid["purchase_units"][0].pop("payments")
    assert paypal.summarize_capture(unpaid)["capture_id"] is None
    assert paypal.summarize_capture(unpaid)["amount"] == "19.00"  # the order's own amount


def test_paid_in_full_needs_the_exact_amount_currency_and_custom_id():
    assert paypal.paid_in_full(paid_order(), "19.00", "USD", "kit:run-1")
    assert paypal.paid_in_full(paid_order(), "19", "usd", "kit:run-1")
    assert paypal.paid_in_full(paid_order(), Decimal("19.0"), "USD", "kit:run-1")
    # The capture's own custom_id may be missing; the purchase unit's counts.
    assert paypal.paid_in_full(paid_order({"custom_id": None}), "19.00", "USD", "kit:run-1")
    assert not paypal.paid_in_full(paid_order(), "20.00", "USD", "kit:run-1")
    assert not paypal.paid_in_full(paid_order(), "18.99", "USD", "kit:run-1")
    assert not paypal.paid_in_full(paid_order(), "19.00", "EUR", "kit:run-1")
    assert not paypal.paid_in_full(paid_order(), "19.00", "USD", "kit:run-2")
    assert not paypal.paid_in_full(paid_order({"status": "PENDING"}), "19.00", "USD", "kit:run-1")
    assert not paypal.paid_in_full(paid_order({"status": "REFUNDED"}), "19.00", "USD", "kit:run-1")
    assert not paypal.paid_in_full(paid_order({"amount": {"currency_code": "USD", "value": "1.90"}}), "19.00", "USD",
                                   "kit:run-1")
    assert not paypal.paid_in_full(paid_order(status="APPROVED"), "19.00", "USD", "kit:run-1")
    twice = paid_order()
    twice["purchase_units"][0]["payments"]["captures"].append({"id": "CAP2", "status": "COMPLETED"})
    assert not paypal.paid_in_full(twice, "19.00", "USD", "kit:run-1")
    assert not paypal.paid_in_full({"id": "ORDER1", "status": "COMPLETED"}, "19.00", "USD", "kit:run-1")
    with pytest.raises(TypeError):
        paypal.paid_in_full(paid_order(), 19.0, "USD", "kit:run-1")


def held_order(authorization: dict | None = None, **order: object) -> dict:
    """An authorized pledge order as authorize_order returns it."""
    hold = {
        "id": "AUTH1", "status": "CREATED", "amount": {"currency_code": "USD", "value": "25.00"},
        "custom_id": "pledge:c1:p1", "create_time": "2026-10-22T10:00:00Z", "expiration_time": "2026-11-20T10:00:00Z",
    }
    return {
        "id": "ORDER7", "status": "COMPLETED",
        "payment_source": {"paypal": {"account_id": "PAYER7", "email_address": "neighbor@example.com"}},
        "purchase_units": [{"reference_id": "c1", "payments": {"authorizations": [{**hold, **(authorization or {})}]}}],
        **order,
    }


def test_summarize_authorization_gives_the_honor_period_and_expiry():
    assert paypal.summarize_authorization(held_order()) == {
        "order_id": "ORDER7", "status": "COMPLETED", "authorization_id": "AUTH1", "authorization_status": "CREATED",
        "amount": "25.00", "currency": "USD", "created_at": "2026-10-22T10:00:00Z",
        "expiration_time": "2026-11-20T10:00:00Z", "honor_period_end": "2026-10-25T10:00:00Z",
        "payer_id": "PAYER7", "custom_id": "pledge:c1:p1",
    }
    # Offsets are read as UTC; an answer without create_time dates it 29 days before the expiry.
    summary = paypal.summarize_authorization(held_order({"create_time": None, "expiration_time": "2026-11-20T02:00:00-08:00"}))
    assert summary["expiration_time"] == "2026-11-20T10:00:00Z"
    assert summary["created_at"] == "2026-10-22T10:00:00Z" and summary["honor_period_end"] == "2026-10-25T10:00:00Z"


def test_authorized_in_full_needs_a_live_hold_of_the_exact_pledge():
    assert paypal.authorized_in_full(held_order(), "25", "USD", "pledge:c1:p1")
    assert not paypal.authorized_in_full(held_order({"status": "VOIDED"}), "25.00", "USD", "pledge:c1:p1")
    assert not paypal.authorized_in_full(held_order({"status": "PENDING"}), "25.00", "USD", "pledge:c1:p1")
    assert not paypal.authorized_in_full(held_order(), "26.00", "USD", "pledge:c1:p1")
    assert not paypal.authorized_in_full(held_order(), "25.00", "CAD", "pledge:c1:p1")
    assert not paypal.authorized_in_full(held_order(), "25.00", "USD", "pledge:c1:p2")
    assert not paypal.authorized_in_full(held_order(status="APPROVED"), "25.00", "USD", "pledge:c1:p1")


def test_capture_from_finds_the_capture_of_an_authorization():
    def capture(capture_id: str, authorization_id: str) -> dict:
        return {"id": capture_id, "status": "COMPLETED", "links": [
            {"rel": "self", "href": f"{API}/v2/payments/captures/{capture_id}"},
            {"rel": "up", "href": f"{API}/v2/payments/authorizations/{authorization_id}"},
        ]}

    order = {"purchase_units": [{"payments": {"captures": [capture("CAP1", "AUTH1"), capture("CAP2", "RE-AUTH2")]}}]}
    assert paypal.capture_from(order, {"AUTH2", "RE-AUTH2"}) == "CAP2"
    assert paypal.capture_from(order, {"AUTH9"}) is None
    assert paypal.capture_from({"purchase_units": [{"payments": {"captures": [{"id": "CAP3"}]}}]}, {"AUTH9"}) == "CAP3"


WEBHOOK_HEADERS = {
    "PAYPAL-AUTH-ALGO": "SHA256withRSA",
    "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT-360caa42-fca2a594-ab66f33d",
    "PAYPAL-TRANSMISSION-ID": "db49fb10-1343-11ef-ac58-e32457403f67",
    "PAYPAL-TRANSMISSION-SIG": "ab2tJk1VCFm4EqdSuKqezr38rTdY3JeRQlw94V1xYAIQVgLScAFn2XLRAhtyo",
    "PAYPAL-TRANSMISSION-TIME": "2026-10-22T05:19:23Z",
}
RAW_EVENT = (b'{"id":"WH-3F562076HD293871E","event_version":"1.0","resource_type":"capture",'
             b'"event_type":"PAYMENT.CAPTURE.COMPLETED","summary":"Payment completed for $ 19.0 USD",'
             b'"resource":{"id":"CAP1","amount":{"value":"19.00","currency_code":"USD"},"status":"COMPLETED"}}')


def test_webhook_signatures_are_verified_by_paypal_with_the_event_as_sent():
    stub = Stub(replies=[httpx.Response(200, json={"verification_status": "SUCCESS"})])
    assert asyncio.run(client_for(stub).verify_webhook_signature(WEBHOOK_HEADERS, RAW_EVENT, "0NH55953DH663215D"))
    request = stub.api()[0]
    assert (request.method, request.url.path) == ("POST", "/v1/notifications/verify-webhook-signature")
    assert RAW_EVENT in request.content  # posted back byte for byte, never re-serialized
    assert json.loads(request.content) == {
        "auth_algo": "SHA256withRSA",
        "cert_url": WEBHOOK_HEADERS["PAYPAL-CERT-URL"],
        "transmission_id": WEBHOOK_HEADERS["PAYPAL-TRANSMISSION-ID"],
        "transmission_sig": WEBHOOK_HEADERS["PAYPAL-TRANSMISSION-SIG"],
        "transmission_time": WEBHOOK_HEADERS["PAYPAL-TRANSMISSION-TIME"],
        "webhook_id": "0NH55953DH663215D",
        "webhook_event": json.loads(RAW_EVENT),
    }
    assert request.headers["paypal-request-id"] and request.headers["prefer"] == "return=representation"


def test_failed_or_incomplete_webhook_signatures_are_rejected():
    lowercase = {key.lower(): value for key, value in WEBHOOK_HEADERS.items()}
    failed = Stub(replies=[httpx.Response(200, json={"verification_status": "FAILURE"})])
    assert not asyncio.run(client_for(failed).verify_webhook_signature(lowercase, json.loads(RAW_EVENT), "WH1"))
    assert b'"webhook_event": {"id":"WH-3F562076HD293871E"' in failed.api()[0].content  # a dict goes compact

    nothing = Stub()
    client = client_for(nothing)
    missing = {key: value for key, value in WEBHOOK_HEADERS.items() if key != "PAYPAL-TRANSMISSION-SIG"}
    assert not asyncio.run(client.verify_webhook_signature(missing, RAW_EVENT, "WH1"))
    assert not asyncio.run(client.verify_webhook_signature(WEBHOOK_HEADERS, RAW_EVENT, ""))
    assert not asyncio.run(client.verify_webhook_signature(WEBHOOK_HEADERS, b"not json", "WH1"))
    assert nothing.requests == []

    malformed = Stub(replies=[failure(400, "VALIDATION_ERROR", "INVALID_PARAMETER_SYNTAX")])
    assert not asyncio.run(client_for(malformed).verify_webhook_signature(WEBHOOK_HEADERS, RAW_EVENT, "WH1"))

    outage = Stub(replies=[failure(503, "SERVICE_UNAVAILABLE")])
    with pytest.raises(PayPalError):  # the delivery fails, so PayPal sends it again later
        asyncio.run(client_for(outage, retries=0).verify_webhook_signature(WEBHOOK_HEADERS, RAW_EVENT, "WH1"))


def test_webhooks_are_registered_and_listed_programmatically():
    stub = Stub(replies=[
        httpx.Response(201, json={"id": "8PT597110X687430LKGECATA", "url": "https://walkin.example/api/paypal/webhook"}),
        httpx.Response(200, json={"webhooks": [{"id": "8PT597110X687430LKGECATA", "event_types": []}, "junk"]}),
        httpx.Response(201, json={"id": "WH2"}),
    ])
    client = client_for(stub)
    created = asyncio.run(client.create_webhook(
        "https://walkin.example/api/paypal/webhook",
        ["PAYMENT.CAPTURE.COMPLETED", "PAYMENT.CAPTURE.REFUNDED", "PAYMENT.CAPTURE.COMPLETED"],
    ))
    hooks = asyncio.run(client.list_webhooks())
    asyncio.run(client.create_webhook("https://walkin.example/other"))
    create, listing, default = stub.api()
    assert created["id"] == "8PT597110X687430LKGECATA"
    assert (create.method, create.url.path) == ("POST", "/v1/notifications/webhooks")
    assert json.loads(create.content) == {"url": "https://walkin.example/api/paypal/webhook", "event_types": [
        {"name": "PAYMENT.CAPTURE.COMPLETED"}, {"name": "PAYMENT.CAPTURE.REFUNDED"}]}
    assert create.headers["paypal-request-id"]
    assert (listing.method, listing.url.path, listing.url.params["anchor_type"]) == (
        "GET", "/v1/notifications/webhooks", "APPLICATION")
    assert hooks == [{"id": "8PT597110X687430LKGECATA", "event_types": []}]
    assert [event["name"] for event in json.loads(default.content)["event_types"]] == list(paypal.WEBHOOK_EVENTS)
    with pytest.raises(ValueError):
        asyncio.run(client.create_webhook("http://walkin.example/hook", ["PAYMENT.CAPTURE.COMPLETED"]))


def test_money_time_and_request_keys():
    assert paypal.money("19", "USD") == "19.00" and paypal.money(Decimal("19.5"), "usd") == "19.50"
    assert paypal.money(25, "USD") == "25.00" and paypal.money("1000", "JPY") == "1000"
    for bad in ("10.5", "0"):
        with pytest.raises(ValueError):
            paypal.money(bad, "JPY")
    with pytest.raises(TypeError):
        paypal.money(19.99, "USD")
    with pytest.raises(TypeError):
        paypal.money(True, "USD")
    assert paypal.parse_time("2026-10-22T14:03:00Z") == datetime(2026, 10, 22, 14, 3, tzinfo=UTC)
    assert paypal.parse_time("2024-05-16T05:19:19.355Z").microsecond == 355000
    assert paypal.parse_time("2026-10-22T07:03:00-07:00") == datetime(2026, 10, 22, 14, 3, tzinfo=UTC)
    assert paypal.parse_time("soon") is None and paypal.parse_time(None) is None
    key = paypal.request_key("capture", "AUTH1")
    assert key == paypal.request_key("capture", "AUTH1") and len(key) == 36
    assert key != paypal.request_key("void", "AUTH1") != paypal.request_key("capture", "AUTH2")


def test_aclose_closes_only_the_client_it_made():
    own = PayPalClient("id", "secret", API)
    asyncio.run(own.aclose())
    assert own._http.is_closed
    shared = httpx.AsyncClient(transport=httpx.MockTransport(Stub()))
    asyncio.run(PayPalClient("id", "secret", API, http_client=shared).aclose())
    assert not shared.is_closed
