"""Founding-supporter campaigns over a fake PayPal: drafts and the owner's terms, pledges held and withdrawn, closing
(funded: every hold collected; short: every hold released), cancelling, the settlement pass on campaigns past their
deadline, the cron endpoint and PayPal's webhook for pledges."""
from __future__ import annotations

import json
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select

from app.db.tables import campaigns, pledges
from tests.commerce_fakes import (
    CRON_SECRET,
    Clock,
    FakePayPal,
    buy_kit,
    configure,
    dev_sign_in,
    make_client,
    run_survey,
    webhook,
)

DISCOUNT = "10% off every visit in the first year"


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    return configure(monkeypatch)


@pytest.fixture
def world():
    """A PayPal and an app sharing one clock, a survey, a signed-in owner and their ready kit for concept 0."""
    clock = Clock()
    paypal = FakePayPal(clock)
    with make_client(paypal=paypal, clock=clock) as client:
        run_id = run_survey(client)
        owner = dev_sign_in(client)
        kit = buy_kit(client, run_id)
        yield {"client": client, "paypal": paypal, "clock": clock, "run_id": run_id, "owner": owner, "kit": kit}


def table(client, which) -> list[dict]:
    async def read() -> list[dict]:
        async with client.app.state.db.engine.connect() as connection:
            return [dict(row) for row in (await connection.execute(select(which))).mappings()]

    return client.portal.call(read)


def terms(world, days: float = 10, **changes) -> dict:
    deadline = (world["clock"].now + timedelta(days=days)).isoformat()
    return {"kit_token": world["kit"]["token"], "amount": "25.00", "goal": 3, "deadline": deadline, **changes}


def start(world, days: float = 10, **changes) -> str:
    client = world["client"]
    body = terms(world, days, **changes)
    draft = client.post("/api/campaigns/draft", json=body).json()
    assert draft["problems"] == []
    created = client.post("/api/campaigns", json={**body, **{key: draft[key] for key in ("title", "pitch", "perks")}})
    assert created.status_code == 200, created.text
    return created.json()["id"]


def pledge(client, campaign_id: str) -> dict:
    order = client.post(f"/api/campaigns/{campaign_id}/pledges")
    assert order.status_code == 200, order.text
    held = client.post(f"/api/campaigns/{campaign_id}/pledges/{order.json()['order_id']}/authorize")
    assert held.status_code == 200, held.text
    return held.json()


def withdraw_token(answer: dict) -> str:
    return parse_qs(urlsplit(answer["withdraw_url"]).query)["withdraw"][0]


def settle(client, at=None) -> list[dict]:
    return client.portal.call(client.app.state.settler.run_once, at)


def test_a_funded_campaign_collects_every_hold_when_its_owner_closes_it(world):
    client, paypal = world["client"], world["paypal"]
    draft = client.post("/api/campaigns/draft", json=terms(world, discount=f"  {DISCOUNT} ")).json()
    assert draft["problems"] == [] and draft["title"] and draft["pitch"]
    assert draft["perks"][0] == DISCOUNT  # the owner's words, first and unchanged
    assert "$25.00" in draft["how_it_works"] and "3 supporters" in draft["how_it_works"]

    body = {**terms(world, discount=DISCOUNT), **{key: draft[key] for key in ("title", "pitch", "perks")}}
    created = client.post("/api/campaigns", json=body).json()
    campaign_id = created["id"]
    assert created == {"id": campaign_id, "url": f"/p/{campaign_id}"}
    again = client.post("/api/campaigns", json=body)
    assert again.status_code == 409 and again.json()["url"] == created["url"]  # one running campaign per kit
    assert client.get(f"/api/kits/{world['kit']['token']}").json()["campaign_url"] == created["url"]

    page = client.get(f"/api/campaigns/{campaign_id}").json()
    assert page == {
        "id": campaign_id, "status": "open", "accepting": True, "name": world["kit"]["name"],
        "neighborhood": page["neighborhood"], "concept": page["concept"], "title": draft["title"],
        "pitch": draft["pitch"], "perks": draft["perks"], "how_it_works": draft["how_it_works"], "amount": "25.00",
        "currency": "USD", "goal": 3, "deadline": page["deadline"], "closed_at": None,
        "progress": {"supporters": 0, "goal": 3, "remaining": 3, "percent": 0, "total": "0.00", "funded": False},
        "is_owner": True, "owner": {"counts": page["owner"]["counts"], "report": None},
        "survey_url": f"/s/{world['run_id']}?sheet=0",
    }
    assert page["concept"]["genre"] and page["concept"]["summary"] and page["deadline"].endswith("Z")
    assert set(page["owner"]["counts"]) >= {"authorized", "captured", "voided"}

    client.post("/api/auth/logout")  # supporters need no account
    held = [pledge(client, campaign_id) for _ in range(3)]
    assert [answer["supporter_number"] for answer in held] == [1, 2, 3]
    assert held[-1]["progress"] == {"supporters": 3, "goal": 3, "remaining": 0, "percent": 100, "total": "75.00", "funded": True}
    assert all(answer["withdraw_url"].startswith(f"/p/{campaign_id}?withdraw=") for answer in held)
    order = paypal.orders[table(client, pledges)[0]["order_id"]]["request"]
    unit = order["purchase_units"][0]
    assert order["intent"] == "AUTHORIZE" and unit["amount"] == {"currency_code": "USD", "value": "25.00"}
    assert unit["custom_id"] == f"pledge:{campaign_id}:{table(client, pledges)[0]['id']}" and unit["reference_id"] == campaign_id
    public = client.get(f"/api/campaigns/{campaign_id}").json()
    assert public["is_owner"] is False and "owner" not in public
    assert all(row["withdraw_token_hash"] and withdraw_token(held[0]) not in str(row) for row in table(client, pledges))
    assert client.post(f"/api/campaigns/{campaign_id}/close").status_code == 401

    dev_sign_in(client)
    closed = client.post(f"/api/campaigns/{campaign_id}/close").json()
    assert (closed["status"], closed["accepting"], closed["progress"]["funded"]) == ("collected", False, True)
    assert closed["closed_at"] and closed["owner"]["report"] == [] and closed["owner"]["counts"]["captured"] == 3
    assert len(paypal.calls(r"/v2/payments/authorizations/[^/]+/capture")) == 3
    assert {row["status"] for row in table(client, pledges)} == {"captured"}
    assert all(row["capture_id"] and row["captured_at"] for row in table(client, pledges))
    assert table(client, campaigns)[0]["funded"] is True
    assert client.post(f"/api/campaigns/{campaign_id}/pledges").status_code == 409
    listed = client.get("/api/me/places").json()["campaigns"]
    assert listed == [{"id": campaign_id, "title": draft["title"], "status": "collected", "supporters": 3, "goal": 3,
                       "deadline": page["deadline"], "url": f"/p/{campaign_id}"}]
    assert client.post(f"/api/campaigns/{campaign_id}/cancel").status_code == 409  # it collected


def test_a_campaign_closed_short_of_its_goal_releases_every_hold(world):
    client, paypal = world["client"], world["paypal"]
    campaign_id = start(world)
    pledge(client, campaign_id)
    closed = client.post(f"/api/campaigns/{campaign_id}/close").json()
    assert closed["status"] == "cancelled" and closed["progress"]["supporters"] == 0
    assert closed["owner"]["counts"]["voided"] == 1 and closed["owner"]["report"] == []
    assert len(paypal.calls(r"/v2/payments/authorizations/[^/]+/void")) == 1
    assert paypal.calls(r"/v2/payments/authorizations/[^/]+/capture") == []
    assert table(client, campaigns)[0]["funded"] is False


def test_supporters_withdraw_while_the_campaign_runs(world):
    client, paypal = world["client"], world["paypal"]
    campaign_id = start(world)
    first, second = pledge(client, campaign_id), pledge(client, campaign_id)
    token = withdraw_token(first)
    withdrawn = client.post(f"/api/campaigns/{campaign_id}/withdraw", json={"token": token})
    assert withdrawn.json() == {"status": "voided", "progress": {
        "supporters": 1, "goal": 3, "remaining": 2, "percent": 33, "total": "25.00", "funded": False}}
    assert client.post(f"/api/campaigns/{campaign_id}/withdraw", json={"token": token}).json()["status"] == "voided"
    assert len(paypal.calls(r"/v2/payments/authorizations/[^/]+/void")) == 1
    assert client.post(f"/api/campaigns/{campaign_id}/withdraw", json={"token": "not-a-token"}).status_code == 404

    world["clock"].advance(days=10, minutes=1)  # past the deadline, before it is settled
    late = client.post(f"/api/campaigns/{campaign_id}/withdraw", json={"token": withdraw_token(second)})
    assert late.status_code == 409 and "closed" in late.json()["detail"]
    assert settle(client) == [{"id": campaign_id, "status": "expired"}]
    # Released by the settlement: the link says so.
    assert client.post(f"/api/campaigns/{campaign_id}/withdraw", json={"token": withdraw_token(second)}).json()["status"] == "voided"


def test_cancelling_releases_every_hold_even_when_the_goal_is_met(world):
    client, paypal = world["client"], world["paypal"]
    campaign_id = start(world)
    for _ in range(3):
        pledge(client, campaign_id)
    dev_sign_in(client, "someone@example.com")
    assert client.post(f"/api/campaigns/{campaign_id}/cancel").status_code == 403
    assert client.post(f"/api/campaigns/{campaign_id}/close").status_code == 403
    dev_sign_in(client)
    cancelled = client.post(f"/api/campaigns/{campaign_id}/cancel").json()
    assert cancelled["status"] == "cancelled" and cancelled["accepting"] is False
    assert len(paypal.calls(r"/v2/payments/authorizations/[^/]+/void")) == 3
    assert paypal.calls(r"/v2/payments/authorizations/[^/]+/capture") == []
    assert client.post(f"/api/campaigns/{campaign_id}/cancel").json()["status"] == "cancelled"
    # The kit may start another campaign now.
    assert start(world) != campaign_id


def test_campaigns_past_their_deadline_settle_in_the_background_pass(world):
    client, paypal, clock = world["client"], world["paypal"], world["clock"]
    funded = start(world, days=5)
    for _ in range(3):
        pledge(client, funded)
    second_kit = buy_kit(client, world["run_id"], 1)
    short = start({**world, "kit": second_kit}, days=2)
    pledge(client, short)
    # One hold PayPal cannot collect for a while (an outage outlasting the client's retries).
    held = [row for row in table(client, pledges) if row["campaign_id"] == funded]
    paypal.unavailable[held[0]["authorization_id"]] = 3

    assert settle(client) == []  # nothing is due yet
    clock.advance(days=2, minutes=1)
    assert settle(client) == [{"id": short, "status": "expired"}]
    clock.advance(days=3)
    assert settle(client) == [{"id": funded, "status": "partial"}]
    row = next(row for row in table(client, campaigns) if row["id"] == funded)
    assert row["funded"] is True and row["report"]  # the decision was kept; the report says one is not collected yet
    page = client.get(f"/api/campaigns/{funded}").json()
    assert page["status"] == "partial" and page["owner"]["report"] == row["report"]

    assert settle(client) == [{"id": funded, "status": "collected"}]  # it keeps collecting
    assert settle(client) == []
    after = {row["id"]: row for row in table(client, pledges)}
    assert all(after[row["id"]]["status"] == "captured" for row in held)
    # Holds past PayPal's 3-day honor period were renewed first, and the renewed holds collected.
    assert all(after[row["id"]]["reauthorization_id"] for row in held)
    captured = {request.url.path.split("/")[-2] for request in paypal.calls(r"/v2/payments/authorizations/[^/]+/capture")}
    assert {after[row["id"]]["reauthorization_id"] for row in held} <= captured
    assert client.get(f"/api/campaigns/{short}").json()["status"] == "expired"


def test_the_cron_endpoint_runs_the_same_settlement(world, monkeypatch):
    client, clock = world["client"], world["clock"]
    campaign_id = start(world, days=1.5)
    pledge(client, campaign_id)
    clock.advance(days=2)
    assert client.post("/api/cron/settle").status_code == 403
    assert client.post("/api/cron/settle", headers={"x-cron-secret": "wrong"}).status_code == 403
    assert client.post("/api/cron/settle", headers={"x-cron-secret": CRON_SECRET}).json() == {
        "settled": [{"id": campaign_id, "status": "expired"}]}
    assert client.post("/api/cron/settle", headers={"x-cron-secret": CRON_SECRET}).json() == {"settled": []}
    configure(monkeypatch, cron_secret="")
    assert client.post("/api/cron/settle", headers={"x-cron-secret": CRON_SECRET}).status_code == 404


def test_the_owner_s_terms_and_words_are_checked(world):
    client = world["client"]
    bad = client.post("/api/campaigns/draft", json=terms(world, days=40, amount="500.00", goal=1)).json()
    assert bad["title"] == "" and bad["perks"] == [] and len(bad["problems"]) == 3
    assert any("27 days" in problem for problem in bad["problems"])
    assert client.post("/api/campaigns/draft", json={**terms(world), "deadline": "next week"}).json()["problems"]
    assert client.post("/api/campaigns/draft", json={**terms(world), "deadline": "2026-11-01T12:00:00"}).json()["problems"]
    too_long = client.post("/api/campaigns/draft", json=terms(world, discount="x" * 81)).json()
    assert too_long["problems"] and "discount" in too_long["problems"][0]

    draft = client.post("/api/campaigns/draft", json=terms(world)).json()
    body = {**terms(world), **{key: draft[key] for key in ("title", "pitch", "perks")}}
    refused = client.post("/api/campaigns", json={**body, "goal": 1})
    assert refused.status_code == 422 and refused.json()["problems"] and refused.json()["detail"]
    named = client.post("/api/campaigns", json={**body, "title": "Better than Harbor Oyster Bar"})
    assert named.status_code == 422 and named.json()["problems"] == ["The title names Harbor Oyster Bar."]
    promised = client.post("/api/campaigns", json={**body, "perks": ["A free coffee on every visit"]})
    assert promised.status_code == 422 and promised.json()["problems"] == ["Perk 1 promises a discount the owner did not set."]
    assert client.post("/api/campaigns", json={**body, "perks": []}).json()["problems"] == ["Add 1 to 4 perks."]
    assert table(client, campaigns) == []

    assert client.post("/api/campaigns/draft", json={**terms(world), "kit_token": "no-such-kit"}).status_code == 404
    dev_sign_in(client, "someone@example.com")
    assert client.post("/api/campaigns/draft", json=terms(world)).status_code == 403
    client.post("/api/auth/logout")
    assert client.post("/api/campaigns/draft", json=terms(world)).status_code == 401
    assert client.get("/api/campaigns/no-such-campaign").status_code == 404


def test_a_declined_pledge_answers_402_and_can_be_retried(world):
    client, paypal = world["client"], world["paypal"]
    campaign_id = start(world)
    order_id = client.post(f"/api/campaigns/{campaign_id}/pledges").json()["order_id"]
    paypal.decline.append(order_id)
    declined = client.post(f"/api/campaigns/{campaign_id}/pledges/{order_id}/authorize")
    assert declined.status_code == 402 and declined.json()["retry"] is True
    held = client.post(f"/api/campaigns/{campaign_id}/pledges/{order_id}/authorize")
    assert held.status_code == 200 and held.json()["supporter_number"] == 1
    again = client.post(f"/api/campaigns/{campaign_id}/pledges/{order_id}/authorize")
    assert again.status_code == 409  # a second answer would hand out another withdraw link
    assert client.post(f"/api/campaigns/{campaign_id}/pledges/UNKNOWN/authorize").status_code == 404
    client.app.state.pledge_limiter.limit = 0
    assert client.post(f"/api/campaigns/{campaign_id}/pledges").status_code == 429


def test_paypal_s_webhook_updates_pledges(world):
    client, paypal = world["client"], world["paypal"]
    campaign_id = start(world)
    pledge(client, campaign_id)
    pledge(client, campaign_id)
    first, second = table(client, pledges)
    voided = {"id": first["authorization_id"], "status": "VOIDED"}
    assert webhook(client, "WH-10", "PAYMENT.AUTHORIZATION.VOIDED", voided).json() == {"status": "ok"}
    captured = {"id": "CAPTURE99", "status": "COMPLETED",
                "supplementary_data": {"related_ids": {"authorization_id": second["authorization_id"]}}}
    assert webhook(client, "WH-11", "PAYMENT.CAPTURE.COMPLETED", captured).json() == {"status": "ok"}
    after = {row["id"]: row for row in table(client, pledges)}
    assert after[first["id"]]["status"] == "voided"
    assert (after[second["id"]]["status"], after[second["id"]]["capture_id"]) == ("captured", "CAPTURE99")
    denied = {"id": "CAPTURE99", "status": "DENIED"}
    assert webhook(client, "WH-12", "PAYMENT.CAPTURE.DENIED", denied).json() == {"status": "ok"}
    after = {row["id"]: row for row in table(client, pledges)}
    assert (after[second["id"]]["status"], after[second["id"]]["error"]) == ("failed", "DENIED")
    assert json.loads(paypal.calls("/v1/notifications/verify-webhook-signature")[-1].content)["webhook_event"]["id"] == "WH-12"
