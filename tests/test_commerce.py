"""The $19 launch kit: checkout to a built kit through a fake PayPal, idempotent capture, declines, pending payments,
rebuilding, refunds within the window, kits a restart cut off, and PayPal's webhook."""
from __future__ import annotations

import asyncio
import json
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db.tables import kits, orders, paypal_events
from app.survey import kit as kit_module
from tests.commerce_fakes import (
    WEBHOOK_ID,
    Clock,
    FakePayPal,
    buy_kit,
    configure,
    dev_sign_in,
    make_client,
    run_survey,
    wait_for_kit,
    webhook,
)


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    return configure(monkeypatch)


def rows(client, table) -> list[dict]:
    async def read() -> list[dict]:
        async with client.app.state.db.engine.connect() as connection:
            return [dict(row) for row in (await connection.execute(select(table))).mappings()]

    return client.portal.call(read)


def test_a_kit_is_bought_with_paypal_and_built_in_the_background():
    paypal = FakePayPal()
    with make_client(paypal=paypal) as client:
        run_id = run_survey(client)
        user = dev_sign_in(client)
        assert client.get("/api/kits/mine", params={"run_id": run_id, "index": 0}).json() == {"kit_url": None}

        order_id = client.post("/api/checkout", json={"run_id": run_id, "index": 0}).json()["order_id"]
        sent = paypal.orders[order_id]["request"]
        unit = sent["purchase_units"][0]
        assert sent["intent"] == "CAPTURE"
        assert unit["amount"] == {"currency_code": "USD", "value": "19.00"}
        assert unit["custom_id"] == f"kit:{run_id}:0:{user['id']}"
        assert unit["description"].startswith("Walk-in launch kit: ")
        [order] = rows(client, orders)
        assert (order["status"], order["user_id"], order["amount_cents"], order["environment"]) == ("created", user["id"], 1900, "sandbox")

        captured = client.post(f"/api/checkout/{order_id}/capture").json()
        token = captured["token"]
        assert captured == {"token": token, "kit_url": f"/k/{token}"} and len(token) >= 43
        page = wait_for_kit(client, token)
        assert page["status"] == "ready" and page["is_owner"] is True and page["error"] is None
        assert page["name"] == unit["description"].removeprefix("Walk-in launch kit: ")
        assert page["survey_url"] == f"/s/{run_id}?sheet=0" and page["index"] == 0 and page["campaign_url"] is None
        assert page["refundable_until"] and page["created_at"].endswith("Z")
        payload = page["kit"]
        assert {"concept", "claims", "copy", "poster", "links", "dossier", "mode", "built_at"} <= set(payload)
        assert payload["dossier"]["sections"] and payload["concept"]["name"] == page["name"]

        [order] = rows(client, orders)
        assert (order["status"], order["capture_id"], order["payer_id"]) == ("completed", paypal.orders[order_id]["purchase_units"][0]["payments"]["captures"][0]["id"], "PAYER1")
        assert client.get("/api/kits/mine", params={"run_id": run_id, "index": 0}).json() == {"kit_url": f"/k/{token}"}
        listed = client.get("/api/me/places").json()["kits"]
        assert listed == [{"token": token, "survey_id": run_id, "index": 0, "name": page["name"], "status": "ready",
                           "created_at": page["created_at"], "url": f"/k/{token}"}]

        # The design sheet the kit needed was made and kept, as POST /api/design would have.
        assert client.post("/api/design", json={"run_id": run_id, "index": 0}).json()["name"]

        # Anyone with the link sees the kit, but not the owner's controls.
        client.post("/api/auth/logout")
        anonymous = client.get(f"/api/kits/{token}").json()
        assert anonymous["is_owner"] is False and anonymous["refundable_until"] is None and anonymous["kit"] == payload
        assert client.get("/api/kits/no-such-kit").status_code == 404


def test_capturing_again_gives_the_same_kit_and_a_kit_is_sold_once():
    paypal = FakePayPal()
    with make_client(paypal=paypal) as client:
        run_id = run_survey(client)
        dev_sign_in(client)
        order_id = client.post("/api/checkout", json={"run_id": run_id, "index": 0}).json()["order_id"]
        first = client.post(f"/api/checkout/{order_id}/capture").json()
        assert client.post(f"/api/checkout/{order_id}/capture").json() == first
        assert len(paypal.calls(r"/v2/checkout/orders/[^/]+/capture")) == 1

        again = client.post("/api/checkout", json={"run_id": run_id, "index": 0})
        assert again.status_code == 409 and again.json()["kit_url"] == first["kit_url"]
        assert again.json()["detail"]
        wait_for_kit(client, first["token"])
        # Another concept of the same survey is another kit.
        assert client.post("/api/checkout", json={"run_id": run_id, "index": 1}).status_code == 200


def test_a_capture_repeated_after_a_lost_answer_still_delivers_the_kit():
    paypal = FakePayPal()
    with make_client(paypal=paypal) as client:
        run_id = run_survey(client)
        dev_sign_in(client)
        order_id = client.post("/api/checkout", json={"run_id": run_id, "index": 0}).json()["order_id"]
        client.portal.call(client.app.state.services.paypal.capture_order, order_id, "another-request")  # paid; answer lost
        captured = client.post(f"/api/checkout/{order_id}/capture")
        assert captured.status_code == 200
        assert wait_for_kit(client, captured.json()["token"])["status"] == "ready"


def test_a_declined_card_answers_402_so_the_buttons_can_restart():
    paypal = FakePayPal()
    with make_client(paypal=paypal) as client:
        run_id = run_survey(client)
        dev_sign_in(client)
        order_id = client.post("/api/checkout", json={"run_id": run_id, "index": 0}).json()["order_id"]
        paypal.decline.append(order_id)
        declined = client.post(f"/api/checkout/{order_id}/capture")
        assert declined.status_code == 402 and declined.json()["retry"] is True and declined.json()["detail"]
        assert rows(client, kits) == [] and rows(client, orders)[0]["status"] == "created"
        # The buyer picks another card in PayPal's buttons, and the same order goes through.
        assert client.post(f"/api/checkout/{order_id}/capture").status_code == 200


def test_checkout_needs_a_signed_in_buyer_a_concept_and_paypal(monkeypatch):
    paypal = FakePayPal()
    with make_client(paypal=paypal) as client:
        run_id = run_survey(client)
        assert client.post("/api/checkout", json={"run_id": run_id, "index": 0}).status_code == 401
        assert client.get("/api/kits/mine", params={"run_id": run_id, "index": 0}).status_code == 401
        dev_sign_in(client)
        assert client.post("/api/checkout", json={"run_id": "nope", "index": 0}).status_code == 404
        assert client.post("/api/checkout", json={"run_id": run_id, "index": 9}).status_code == 404
        order_id = client.post("/api/checkout", json={"run_id": run_id, "index": 0}).json()["order_id"]

        dev_sign_in(client, "someone@example.com")
        assert client.post(f"/api/checkout/{order_id}/capture").status_code == 404  # only the buyer captures
        assert client.post("/api/checkout/UNKNOWN/capture").status_code == 404
        assert paypal.calls(r"/v2/checkout/orders/[^/]+/capture") == []

        client.app.state.checkout_limiter.limit = 0
        assert client.post("/api/checkout", json={"run_id": run_id, "index": 1}).status_code == 429

    with make_client() as client:  # no PayPal: nothing is for sale
        run_id = run_survey(client)
        dev_sign_in(client)
        assert client.post("/api/checkout", json={"run_id": run_id, "index": 0}).status_code == 503


def test_the_owner_refunds_within_14_days_through_paypal():
    paypal, clock = FakePayPal(), Clock()
    paypal.clock = clock
    with make_client(paypal=paypal, clock=clock) as client:
        run_id = run_survey(client)
        dev_sign_in(client)
        first = buy_kit(client, run_id, 0)
        second = buy_kit(client, run_id, 1)

        dev_sign_in(client, "someone@example.com")
        assert client.post(f"/api/kits/{first['token']}/refund").status_code == 403
        dev_sign_in(client)

        clock.advance(days=13, hours=23)
        refunded = client.post(f"/api/kits/{first['token']}/refund")
        assert refunded.status_code == 200 and refunded.json() == {"status": "refunded"}
        [refund] = paypal.calls(r"/v2/payments/captures/[^/]+/refund")
        assert paypal.body(refund)["note_to_payer"] and refund.headers["paypal-request-id"]
        page = client.get(f"/api/kits/{first['token']}").json()
        assert page["status"] == "refunded" and page["kit"] is None and page["refundable_until"] is None
        assert client.get("/api/kits/mine", params={"run_id": run_id, "index": 0}).json() == {"kit_url": None}
        assert client.post(f"/api/kits/{first['token']}/refund").json() == {"status": "refunded"}  # once
        assert len(paypal.calls(r"/v2/payments/captures/[^/]+/refund")) == 1
        order_of = {row["token"]: row["order_id"] for row in rows(client, kits)}
        status_of = {row["id"]: row["status"] for row in rows(client, orders)}
        assert (status_of[order_of[first["token"]]], status_of[order_of[second["token"]]]) == ("refunded", "completed")

        clock.advance(hours=2)  # past 14 days for the second kit
        late = client.post(f"/api/kits/{second['token']}/refund")
        assert late.status_code == 409 and "14 days" in late.json()["detail"]
        assert client.get(f"/api/kits/{second['token']}").json()["refundable_until"] is None
        # A refunded kit can be bought again.
        assert client.post("/api/checkout", json={"run_id": run_id, "index": 0}).status_code == 200


def test_a_kit_that_failed_to_build_is_built_again_on_request(monkeypatch):
    real = kit_module.build_kit
    calls = []

    async def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("the model broke")
        return await real(*args, **kwargs)

    monkeypatch.setattr(kit_module, "build_kit", flaky)
    with make_client(paypal=FakePayPal()) as client:
        run_id = run_survey(client)
        dev_sign_in(client)
        order_id = client.post("/api/checkout", json={"run_id": run_id, "index": 0}).json()["order_id"]
        token = client.post(f"/api/checkout/{order_id}/capture").json()["token"]
        failed = wait_for_kit(client, token)
        assert failed["status"] == "failed" and failed["kit"] is None and "Try again" in failed["error"]
        assert client.post(f"/api/kits/{token}/retry").status_code == 202
        assert wait_for_kit(client, token)["status"] == "ready"
        assert client.post(f"/api/kits/{token}/retry").status_code == 409  # only failed kits


def test_kits_a_restart_cut_off_are_built_at_the_next_start(monkeypatch):
    real = kit_module.build_kit
    hold = {"on": True}

    async def slow(*args, **kwargs):
        while hold["on"]:
            await asyncio.sleep(0.05)
        return await real(*args, **kwargs)

    monkeypatch.setattr(kit_module, "build_kit", slow)
    with make_client(paypal=FakePayPal()) as client:
        run_id = run_survey(client)
        dev_sign_in(client)
        order_id = client.post("/api/checkout", json={"run_id": run_id, "index": 0}).json()["order_id"]
        token = client.post(f"/api/checkout/{order_id}/capture").json()["token"]
        assert client.get(f"/api/kits/{token}").json()["status"] == "building"
    hold["on"] = False  # the server stopped mid-build; the next one picks it up
    with make_client(paypal=FakePayPal()) as client:
        assert wait_for_kit(client, token)["status"] == "ready"


def test_a_payment_paypal_reviews_delivers_the_kit_when_its_webhook_says_completed():
    paypal = FakePayPal()
    paypal.capture_status = "PENDING"
    with make_client(paypal=paypal) as client:
        run_id = run_survey(client)
        dev_sign_in(client)
        order_id = client.post("/api/checkout", json={"run_id": run_id, "index": 0}).json()["order_id"]
        pending = client.post(f"/api/checkout/{order_id}/capture")
        assert pending.status_code == 409 and pending.json()["pending"] is True
        assert rows(client, orders)[0]["status"] == "pending" and rows(client, kits) == []

        resource = paypal.complete_capture(order_id)
        assert webhook(client, "WH-1", "PAYMENT.CAPTURE.COMPLETED", resource).json() == {"status": "ok"}
        kit_url = client.get("/api/kits/mine", params={"run_id": run_id, "index": 0}).json()["kit_url"]
        assert kit_url and wait_for_kit(client, kit_url.rsplit("/", 1)[-1])["status"] == "ready"
        assert rows(client, orders)[0]["status"] == "completed"


def test_webhooks_are_verified_with_paypal_and_handled_once(monkeypatch):
    paypal = FakePayPal()
    with make_client(paypal=paypal) as client:
        run_id = run_survey(client)
        dev_sign_in(client)
        kit = buy_kit(client, run_id)
        capture_id = rows(client, orders)[0]["capture_id"]
        refund = {"id": "REFUND9", "status": "COMPLETED", "amount": {"currency_code": "USD", "value": "19.00"},
                  "links": [{"rel": "up", "href": f"https://api.sandbox.paypal.com/v2/payments/captures/{capture_id}"}]}

        paypal.webhook_genuine = False
        assert webhook(client, "WH-2", "PAYMENT.CAPTURE.REFUNDED", refund).status_code == 400
        assert rows(client, paypal_events) == [] and client.get(f"/api/kits/{kit['token']}").json()["status"] == "ready"

        paypal.webhook_genuine = True
        assert webhook(client, "WH-2", "PAYMENT.CAPTURE.REFUNDED", refund).json() == {"status": "ok"}
        assert client.get(f"/api/kits/{kit['token']}").json()["status"] == "refunded"  # refunded from PayPal's side
        assert webhook(client, "WH-2", "PAYMENT.CAPTURE.REFUNDED", refund).json() == {"status": "duplicate"}
        [event] = rows(client, paypal_events)
        assert (event["id"], event["event_type"], event["resource_id"]) == ("WH-2", "PAYMENT.CAPTURE.REFUNDED", "REFUND9")
        verified = paypal.calls("/v1/notifications/verify-webhook-signature")[-1]
        assert json.loads(verified.content)["webhook_id"] == WEBHOOK_ID
        assert webhook(client, "WH-3", "CHECKOUT.ORDER.APPROVED", {"id": "ORDER77"}).json() == {"status": "ok"}

    configure(monkeypatch, paypal_webhook_id="")
    with make_client(paypal=paypal) as client:
        assert webhook(client, "WH-4", "PAYMENT.CAPTURE.REFUNDED", {}).status_code == 404


def test_a_kit_with_a_running_campaign_is_not_refunded_until_the_campaign_is_cancelled():
    paypal, clock = FakePayPal(), Clock()
    paypal.clock = clock
    with make_client(paypal=paypal, clock=clock) as client:
        run_id = run_survey(client)
        dev_sign_in(client)
        kit = buy_kit(client, run_id)
        deadline = (clock.now + timedelta(days=10)).isoformat()
        draft = client.post("/api/campaigns/draft", json={"kit_token": kit["token"], "amount": "25.00", "goal": 3,
                                                          "deadline": deadline}).json()
        created = client.post("/api/campaigns", json={"kit_token": kit["token"], "amount": "25.00", "goal": 3,
                                                      "deadline": deadline, "title": draft["title"],
                                                      "pitch": draft["pitch"], "perks": draft["perks"]}).json()
        assert client.get(f"/api/kits/{kit['token']}").json()["campaign_url"] == created["url"]
        blocked = client.post(f"/api/kits/{kit['token']}/refund")
        assert blocked.status_code == 409 and "Cancel" in blocked.json()["detail"]
        assert client.post(f"/api/campaigns/{created['id']}/cancel").json()["status"] == "cancelled"
        assert client.post(f"/api/kits/{kit['token']}/refund").json() == {"status": "refunded"}


def test_config_tells_the_page_how_paypal_takes_payments(monkeypatch):
    with make_client(paypal=FakePayPal()) as client:
        assert client.get("/api/config").json()["paypal"] == {
            "enabled": True, "client_id": "test-paypal-client", "environment": "sandbox", "currency": "USD",
            "kit_price": "19.00",
        }
    configure(monkeypatch, kit_price="25")
    with make_client() as client:
        assert client.get("/api/config").json()["paypal"] == {
            "enabled": False, "client_id": None, "environment": "sandbox", "currency": "USD", "kit_price": "25.00",
        }


def test_paid_pages_and_paypal_s_sdk_get_through_the_security_headers():
    with make_client() as client:
        for path in ("/k/some-kit", "/k/some-kit/dossier", "/p/some-campaign"):
            response = client.get(path)
            assert response.status_code == 200 and response.headers["content-type"].startswith("text/html")
            policy = dict(part.strip().split(" ", 1) for part in response.headers["content-security-policy"].split(";"))
            for directive in ("script-src", "style-src", "connect-src", "frame-src", "child-src"):
                assert "https://*.paypal.com" in policy[directive] and "https://*.paypalobjects.com" in policy[directive]
        # PayPal and the scheduled job call from elsewhere, and prove themselves otherwise; pages from elsewhere may not.
        elsewhere = {"origin": "https://evil.example.com"}
        assert client.post("/api/cron/settle", headers=elsewhere).json() == {"detail": "Wrong cron secret."}
        assert client.post("/api/paypal/webhook", headers=elsewhere).status_code == 404  # no PayPal client here
        assert client.post("/api/checkout", headers=elsewhere, json={"run_id": "x", "index": 0}).status_code == 403


def test_an_account_whose_survey_a_kit_was_bought_for_is_not_deleted_from_under_the_order():
    with make_client(paypal=FakePayPal()) as client:
        run_id = run_survey(client)
        dev_sign_in(client)  # the survey run before signing in is now the user's
        buy_kit(client, run_id)
        refused = client.delete("/api/me")
        assert refused.status_code == 409 and "Contact us" in refused.json()["detail"]
        assert client.get("/api/me").json()["user"] and client.get(f"/api/runs/{run_id}").status_code == 200
