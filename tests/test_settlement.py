"""Walk-in Founders' settlement over a fake PayPal: a funded campaign collects every hold (renewing those past PayPal's
3-day honor period) and pays its owner the net collected total once; a campaign short of its goal, or cancelled,
releases every hold; a settlement cut short resumes on its stored decision; captures PayPal reviews are paid out once
completed; the in-app loop, the cron endpoint and PayPal's webhooks (verified, handled once) keep it all in step."""
from __future__ import annotations

import time
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.db.tables import campaigns, payouts, pledges, surveys
from app.payments import pledges as rules
from tests.founders_fakes import (
    CRON_SECRET,
    WEBHOOK_HEADERS,
    Clock,
    FakePayPal,
    configure,
    dev_sign_in,
    make_client,
    race,
    ready_kit,
    run_survey,
    webhook,
)

EMAIL = "olive.owner@example.com"
NET = "23.64"  # $25.00 after the fake PayPal's fee of 3.49% + $0.49


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    return configure(monkeypatch)


@pytest.fixture
def world():
    clock = Clock()
    paypal = FakePayPal(clock)
    with make_client(paypal=paypal, clock=clock) as client:
        run_id = run_survey(client)
        kit = ready_kit(client, run_id)
        dev_sign_in(client)
        yield {"client": client, "paypal": paypal, "clock": clock, "run_id": run_id, "kit": kit}


def table(client, which) -> list[dict]:
    async def read() -> list[dict]:
        async with client.app.state.db.engine.connect() as connection:
            return [dict(row) for row in (await connection.execute(select(which))).mappings()]

    return client.portal.call(read)


def change(client, which, where, **values) -> None:
    async def write() -> None:
        async with client.app.state.db.engine.begin() as connection:
            await connection.execute(update(which).where(where).values(**values))

    client.portal.call(write)


def start(world, days: float = 10, goal: int = 3, kit: dict | None = None) -> str:
    client = world["client"]
    body = {"kit_token": (kit or world["kit"])["token"], "amount": "25.00", "goal": goal,
            "deadline": (world["clock"].now + timedelta(days=days)).isoformat(), "perk": None}
    drafted = client.post("/api/campaigns/draft", json=body).json()
    created = client.post("/api/campaigns", json={**body, "payout_email": EMAIL,
                                                  **{key: drafted[key] for key in ("title", "pitch", "perks")}})
    assert created.status_code == 200, created.text
    return created.json()["id"]


def pledge(client, campaign_id: str) -> str:
    order_id = client.post(f"/api/campaigns/{campaign_id}/pledges").json()["order_id"]
    held = client.post(f"/api/campaigns/{campaign_id}/pledges/{order_id}/authorize")
    assert held.status_code == 200 and held.json()["status"] == "authorized", held.text
    return order_id


def settle(client) -> dict:
    return client.portal.call(client.app.state.settler.run_once)


def by_order(client) -> dict[str, dict]:
    return {row["order_id"]: row for row in table(client, pledges)}


def test_a_funded_campaign_closed_early_collects_every_hold_and_pays_its_owner_once(world):
    client, paypal = world["client"], world["paypal"]
    campaign_id = start(world)
    orders = [pledge(client, campaign_id) for _ in range(3)]
    closed = client.post(f"/api/campaigns/{campaign_id}/close").json()
    assert (closed["status"], closed["accepting"], closed["progress"]["funded"]) == ("collected", False, True)
    assert closed["closed_at"] and closed["owner"]["report"] == [] and closed["owner"]["counts"]["captured"] == 3
    assert closed["progress"]["total"] == "75.00"
    # Within PayPal's 3-day honor period, every hold is captured as it is.
    assert paypal.calls(r"/v2/payments/authorizations/[^/]+/reauthorize") == []
    assert len(paypal.calls(r"/v2/payments/authorizations/[^/]+/capture")) == 3
    rows = by_order(client)
    assert all(rows[order]["status"] == "captured" and rows[order]["capture_status"] == "COMPLETED" for order in orders)
    assert all(rows[order]["net_cents"] == 2364 and rows[order]["captured_at"] for order in orders)
    assert table(client, campaigns)[0]["funded"] is True

    # The owner is paid the net collected total, by email, once: the campaign's id is the payout's sender_batch_id.
    [sent] = paypal.calls("/v1/payments/payouts")
    body = paypal.body(sent)
    assert body["sender_batch_header"]["sender_batch_id"] == campaign_id
    [item] = body["items"]
    assert (item["receiver"], item["amount"], item["recipient_type"]) == (EMAIL, {"currency": "USD", "value": "70.92"}, "EMAIL")
    assert closed["owner"]["payout"] == {"status": "pending", "amount": "70.92", "email": "o***@example.com"}
    [payout] = table(client, payouts)
    assert (payout["status"], payout["amount_cents"], payout["email"], payout["batch_id"]) == (
        "pending", 7092, EMAIL, next(iter(paypal.payouts)))

    assert settle(client) == {"settled": [], "payouts": [{"id": campaign_id, "status": "pending"}]}  # asks, never resends
    assert len(paypal.calls("/v1/payments/payouts")) == 1
    paid = paypal.finish_payout(payout["batch_id"])
    assert webhook(client, "WH-PAID", "PAYMENT.PAYOUTS-ITEM.SUCCEEDED", paid).json() == {"status": "ok"}
    page = client.get(f"/api/campaigns/{campaign_id}").json()
    assert page["owner"]["payout"] == {"status": "paid", "amount": "70.92", "email": "o***@example.com"}
    assert table(client, payouts)[0]["paypal_status"] == "SUCCESS"
    assert settle(client) == {"settled": [], "payouts": []}  # nothing left to do
    assert len(paypal.calls("/v1/payments/payouts")) == 1
    assert client.post(f"/api/campaigns/{campaign_id}/pledges").status_code == 409
    assert client.post(f"/api/campaigns/{campaign_id}/cancel").status_code == 409  # it collected
    assert client.post(f"/api/campaigns/{campaign_id}/close").json()["status"] == "collected"  # idempotent
    assert client.get("/api/me/places").json()["campaigns"][0]["status"] == "collected"


def test_at_the_deadline_old_holds_are_renewed_and_a_refused_capture_leaves_it_partial(world):
    client, paypal, clock = world["client"], world["paypal"], world["clock"]
    campaign_id = start(world, days=5)
    orders = [pledge(client, campaign_id) for _ in range(4)]
    refused = by_order(client)[orders[0]]["authorization_id"]
    paypal.refuse[refused] = "INSTRUMENT_DECLINED"

    assert settle(client) == {"settled": [], "payouts": []}  # nothing is due yet
    clock.advance(days=5, minutes=1)
    assert settle(client) == {"settled": [{"id": campaign_id, "status": "partial"}],
                              "payouts": [{"id": campaign_id, "status": "pending"}]}
    # Every hold was past its 3-day honor period: renewed first, and the renewed hold captured.
    assert len(paypal.calls(r"/v2/payments/authorizations/[^/]+/reauthorize")) == 4
    captured = {request.url.path.split("/")[-2] for request in paypal.calls(r"/v2/payments/authorizations/[^/]+/capture")}
    rows = by_order(client)
    assert all(rows[order]["reauthorization_id"] in captured for order in orders)
    assert [rows[order]["status"] for order in orders] == ["failed", "captured", "captured", "captured"]
    assert rows[orders[0]]["error"] == "INSTRUMENT_DECLINED"
    page = client.get(f"/api/campaigns/{campaign_id}").json()
    assert page["status"] == "partial" and page["owner"]["report"] == [
        "1 pledge could not be collected: the card or bank declined the payment (INSTRUMENT_DECLINED)."]
    assert page["owner"]["payout"]["amount"] == "70.92"  # what was collected, after PayPal's fees
    assert table(client, campaigns)[0]["funded"] is True
    assert settle(client)["settled"] == []  # a refused pledge is not retried


def test_short_of_its_goal_at_the_deadline_every_hold_is_released(world):
    client, paypal, clock = world["client"], world["paypal"], world["clock"]
    campaign_id = start(world, days=2)
    pledge(client, campaign_id)
    clock.advance(days=2, minutes=1)
    assert settle(client) == {"settled": [{"id": campaign_id, "status": "expired"}], "payouts": []}
    assert len(paypal.calls(r"/v2/payments/authorizations/[^/]+/void")) == 1
    assert paypal.calls(r"/v2/payments/authorizations/[^/]+/capture") == [] and paypal.calls("/v1/payments/payouts") == []
    page = client.get(f"/api/campaigns/{campaign_id}").json()
    assert (page["status"], page["owner"]["counts"]["voided"], page["owner"]["payout"]["status"]) == ("expired", 1, "none")
    assert table(client, campaigns)[0]["funded"] is False
    assert settle(client) == {"settled": [], "payouts": []}


def test_a_settlement_cut_short_resumes_on_the_decision_it_stored(world, monkeypatch):
    client, paypal, clock = world["client"], world["paypal"], world["clock"]
    campaign_id = start(world, days=1)
    orders = [pledge(client, campaign_id) for _ in range(3)]
    real = rules.settle

    async def crash(campaign, found, client_, now, *, record=None, **options):
        await record(rules.decide_funding(campaign, found, now))  # the decision is stored first
        raise RuntimeError("the server stopped here")

    monkeypatch.setattr(rules, "settle", crash)
    clock.advance(days=1, minutes=1)
    assert settle(client) == {"settled": [], "payouts": []}  # the pass logged the failure and went on
    [row] = table(client, campaigns)
    assert (row["status"], row["funded"]) == ("funded", True)
    assert paypal.calls(r"/v2/payments/authorizations/[^/]+/capture") == []

    # Meanwhile one hold is released outside the app: the campaign is short of its goal now, but its decision stands.
    voided = by_order(client)[orders[0]]["authorization_id"]
    paypal.authorizations[voided]["status"] = "VOIDED"
    assert webhook(client, "WH-VOID", "PAYMENT.AUTHORIZATION.VOIDED", {"id": voided, "status": "VOIDED"}).json() == {
        "status": "ok"}
    monkeypatch.setattr(rules, "settle", real)
    result = settle(client)
    assert result["settled"] == [{"id": campaign_id, "status": "collected"}]
    assert [by_order(client)[order]["status"] for order in orders] == ["voided", "captured", "captured"]
    assert paypal.calls(r"/v2/payments/authorizations/[^/]+/void") == []  # it never released the others
    assert result["payouts"] == [{"id": campaign_id, "status": "pending"}]
    assert paypal.body(paypal.calls("/v1/payments/payouts")[0])["items"][0]["amount"]["value"] == "47.28"


def test_holds_paypal_cannot_collect_for_a_while_are_tried_again_and_paid_out_after(world):
    client, paypal, clock = world["client"], world["paypal"], world["clock"]
    campaign_id = start(world, days=1)
    orders = [pledge(client, campaign_id) for _ in range(3)]
    paypal.unavailable[by_order(client)[orders[0]]["authorization_id"]] = 3  # longer than the client's retries
    clock.advance(days=1, minutes=1)
    first = settle(client)
    assert first == {"settled": [{"id": campaign_id, "status": "partial"}], "payouts": []}  # no payout while collecting
    assert table(client, campaigns)[0]["report"] == [
        "1 pledge is not collected yet (SERVICE_UNAVAILABLE); the next settlement tries again."]
    assert settle(client) == {"settled": [{"id": campaign_id, "status": "collected"}],
                              "payouts": [{"id": campaign_id, "status": "pending"}]}
    assert paypal.body(paypal.calls("/v1/payments/payouts")[0])["items"][0]["amount"]["value"] == "70.92"


def test_captures_paypal_reviews_are_paid_out_once_completed(world):
    client, paypal = world["client"], world["paypal"]
    paypal.capture_status = "PENDING"
    campaign_id = start(world)
    for _ in range(3):
        pledge(client, campaign_id)
    closed = client.post(f"/api/campaigns/{campaign_id}/close").json()
    assert closed["status"] == "collected" and closed["owner"]["payout"]["status"] == "none"
    assert closed["owner"]["report"] == ["3 payments are pending at PayPal, which completes or denies them later."]
    assert paypal.calls("/v1/payments/payouts") == []
    assert {row["capture_status"] for row in table(client, pledges)} == {"PENDING"}

    # PayPal completes one (its webhook says so), then the pass asks about the others.
    capture_ids = [row["capture_id"] for row in table(client, pledges)]
    done = paypal.complete_capture(capture_ids[0])
    assert webhook(client, "WH-CAP", "PAYMENT.CAPTURE.COMPLETED", done).json() == {"status": "ok"}
    assert table(client, pledges)[0]["net_cents"] == 2364
    assert paypal.calls("/v1/payments/payouts") == []  # two are still under review
    for capture_id in capture_ids[1:]:
        paypal.complete_capture(capture_id)
    assert settle(client) == {"settled": [{"id": campaign_id, "status": "collected"}],
                              "payouts": [{"id": campaign_id, "status": "pending"}]}
    assert len(paypal.calls(r"/v2/payments/captures/[^/]+", method="GET")) >= 2
    assert paypal.body(paypal.calls("/v1/payments/payouts")[0])["items"][0]["amount"]["value"] == "70.92"


def test_a_payout_survives_outages_lost_answers_and_refusals_without_paying_twice(world):
    client, paypal = world["client"], world["paypal"]
    campaign_id = start(world)
    for _ in range(3):
        pledge(client, campaign_id)
    paypal.payout_outage = 3  # PayPal is down longer than the client's retries
    closed = client.post(f"/api/campaigns/{campaign_id}/close").json()
    assert closed["owner"]["payout"] == {"status": "pending", "amount": "70.92", "email": "o***@example.com"}
    [payout] = table(client, payouts)
    assert payout["batch_id"] is None and "SERVICE_UNAVAILABLE" in payout["error"]
    assert settle(client)["payouts"] == [{"id": campaign_id, "status": "pending"}]
    [payout] = table(client, payouts)
    assert payout["batch_id"] and payout["error"] is None
    keys = {request.headers["paypal-request-id"] for request in paypal.calls("/v1/payments/payouts")}
    assert len(keys) == 1 and len(paypal.payouts) == 1  # the same request each time, and one batch

    # The answer is lost (the batch id was never stored) and PayPal no longer remembers the request: the duplicate
    # sender_batch_id leads back to the original payout.
    change(client, payouts, payouts.c.campaign_id == campaign_id, batch_id=None)
    paypal._answers.clear()
    assert settle(client)["payouts"] == [{"id": campaign_id, "status": "pending"}]
    assert table(client, payouts)[0]["batch_id"] == payout["batch_id"] and len(paypal.payouts) == 1
    settle(client)  # follows the original batch
    assert paypal.calls(f"/v1/payments/payouts/{payout['batch_id']}", method="GET")
    failed = paypal.finish_payout(payout["batch_id"], "FAILED")
    assert webhook(client, "WH-FAILED", "PAYMENT.PAYOUTS-ITEM.FAILED", failed).json() == {"status": "ok"}
    assert client.get(f"/api/campaigns/{campaign_id}").json()["owner"]["payout"]["status"] == "failed"
    assert table(client, payouts)[0]["error"] == "RECEIVER_UNREGISTERED"
    assert settle(client)["payouts"] == []  # a failed payout is the owner's to sort out with PayPal


def test_a_payout_paypal_refuses_is_marked_failed(world):
    client, paypal = world["client"], world["paypal"]
    paypal.payout_refusal = "INSUFFICIENT_FUNDS"
    campaign_id = start(world)
    for _ in range(3):
        pledge(client, campaign_id)
    closed = client.post(f"/api/campaigns/{campaign_id}/close").json()
    assert closed["owner"]["payout"]["status"] == "failed"
    assert "INSUFFICIENT_FUNDS" in table(client, payouts)[0]["error"]
    assert settle(client) == {"settled": [], "payouts": []}
    assert len(paypal.calls("/v1/payments/payouts")) == 1


def test_webhooks_are_verified_on_the_raw_body_and_handled_once(world):
    client, paypal = world["client"], world["paypal"]
    campaign_id = start(world)
    first, second = pledge(client, campaign_id), pledge(client, campaign_id)
    rows = by_order(client)

    paypal.webhook_genuine = False
    forged = webhook(client, "WH-1", "PAYMENT.AUTHORIZATION.VOIDED", {"id": rows[first]["authorization_id"]})
    assert forged.status_code == 400 and by_order(client)[first]["status"] == "authorized"
    paypal.webhook_genuine = True
    unsigned = client.post("/api/paypal/webhook", content=b'{"id": "WH-2", "event_type": "X", "resource": {}}')
    assert unsigned.status_code == 400  # without PayPal's signature headers it is never even sent to PayPal
    paypal.verify_outage = True
    assert webhook(client, "WH-3", "PAYMENT.AUTHORIZATION.VOIDED", {"id": "AUTH1"}).status_code == 503
    paypal.verify_outage = False
    sent = paypal.calls("/v1/notifications/verify-webhook-signature")[-1]
    assert paypal.body(sent)["webhook_id"] == "WH-TEST-1" and paypal.body(sent)["webhook_event"]["id"] == "WH-3"

    voided = webhook(client, "WH-4", "PAYMENT.AUTHORIZATION.VOIDED", {"id": rows[first]["authorization_id"]})
    assert voided.json() == {"status": "ok"} and by_order(client)[first]["status"] == "voided"
    assert webhook(client, "WH-4", "PAYMENT.AUTHORIZATION.VOIDED", {"id": "anything"}).json() == {"status": "duplicate"}
    assert webhook(client, "WH-5", "BILLING.SUBSCRIPTION.CREATED", {"id": "I-1"}).json() == {"status": "ignored"}
    assert webhook(client, "WH-5", "BILLING.SUBSCRIPTION.CREATED", {"id": "I-1"}).json() == {"status": "duplicate"}
    junk = client.post("/api/paypal/webhook", content=b'{"no": "id"}', headers=WEBHOOK_HEADERS)
    assert junk.status_code == 400

    captured = {"id": "CAPTURE99", "status": "COMPLETED",
                "supplementary_data": {"related_ids": {"authorization_id": rows[second]["authorization_id"]}},
                "seller_receivable_breakdown": FakePayPal.breakdown("25.00")}
    assert webhook(client, "WH-6", "PAYMENT.CAPTURE.COMPLETED", captured).json() == {"status": "ok"}
    row = by_order(client)[second]
    assert (row["status"], row["capture_id"], row["capture_status"], row["net_cents"]) == ("captured", "CAPTURE99", "COMPLETED", 2364)
    refund = {"id": "REFUND1", "status": "COMPLETED",
              "links": [{"rel": "up", "href": "https://api-m.sandbox.paypal.com/v2/payments/captures/CAPTURE99"}]}
    assert webhook(client, "WH-7", "PAYMENT.CAPTURE.REFUNDED", refund).json() == {"status": "ok"}
    assert (by_order(client)[second]["status"], by_order(client)[second]["error"]) == ("refunded", "REFUNDED")


def test_a_pledge_approved_in_paypal_is_held_from_the_webhook_when_the_supporter_never_came_back(world):
    client = world["client"]
    campaign_id = start(world)
    order_id = client.post(f"/api/campaigns/{campaign_id}/pledges", json={"flow": "redirect"}).json()["order_id"]
    approved = webhook(client, "WH-APPROVED", "CHECKOUT.ORDER.APPROVED", {"id": order_id, "status": "APPROVED"})
    assert approved.json() == {"status": "ok"}
    assert by_order(client)[order_id]["status"] == "authorized"
    page = client.get(f"/api/campaigns/{campaign_id}").json()
    assert page["progress"]["supporters"] == 1
    # The supporter's own return to the page is idempotent.
    assert client.post(f"/api/campaigns/{campaign_id}/pledges/{order_id}/authorize").json()["status"] == "authorized"


def test_the_cron_endpoint_runs_the_same_pass(world, monkeypatch):
    client, clock = world["client"], world["clock"]
    campaign_id = start(world, days=1.5)
    pledge(client, campaign_id)
    clock.advance(days=2)
    assert client.post("/api/cron/settle").status_code == 403
    assert client.post("/api/cron/settle", headers={"x-cron-secret": "wrong"}).status_code == 403
    assert client.post("/api/cron/settle", headers={"x-cron-secret": CRON_SECRET}).json() == {
        "settled": [{"id": campaign_id, "status": "expired"}], "payouts": []}
    assert client.post("/api/cron/settle", headers={"x-cron-secret": CRON_SECRET}).json() == {"settled": [], "payouts": []}
    configure(monkeypatch, cron_secret="")
    assert client.post("/api/cron/settle", headers={"x-cron-secret": CRON_SECRET}).status_code == 404


def test_the_app_settles_on_its_own_in_the_background():
    clock = Clock()
    paypal = FakePayPal(clock)
    with make_client(paypal=paypal, clock=clock, settle_every=0.05) as client:
        run_id = run_survey(client)
        world = {"client": client, "clock": clock, "kit": ready_kit(client, run_id)}
        dev_sign_in(client)
        campaign_id = start(world, days=1)
        pledge(client, campaign_id)
        clock.advance(days=1, minutes=1)
        deadline = time.monotonic() + 10
        while client.get(f"/api/campaigns/{campaign_id}").json()["status"] == "open" and time.monotonic() < deadline:
            time.sleep(0.05)
        assert client.get(f"/api/campaigns/{campaign_id}").json()["status"] == "expired"
        assert len(paypal.calls(r"/v2/payments/authorizations/[^/]+/void")) == 1


def test_surveys_behind_campaigns_are_kept_from_the_purge(monkeypatch, database_url):
    clock = Clock()
    with make_client(paypal=FakePayPal(clock), clock=clock, database_url=database_url) as client:
        run_id = run_survey(client)  # signed out: nobody keeps it in My places
        world = {"client": client, "clock": clock, "kit": ready_kit(client, run_id)}
        dev_sign_in(client)
        start(world)
        other = run_survey(client)
        change(client, surveys, surveys.c.id.in_([run_id, other]), user_id=None,
               created_at=clock.now - timedelta(days=90))
    with make_client(paypal=FakePayPal(clock), clock=clock, database_url=database_url) as client:
        kept = {row["id"] for row in table(client, surveys)}
        assert run_id in kept and other not in kept
        assert len(table(client, campaigns)) == 1


def test_paypal_s_clock_running_ahead_never_makes_a_pledge_late(world):
    client, paypal, clock = world["client"], world["paypal"], world["clock"]
    paypal.clock = lambda: clock.now + timedelta(minutes=2)  # PayPal's timestamps run two minutes ahead of ours
    campaign_id = start(world)
    for _ in range(3):
        pledge(client, campaign_id)
    closed = client.post(f"/api/campaigns/{campaign_id}/close").json()
    assert closed["status"] == "collected" and closed["owner"]["counts"]["captured"] == 3
    assert paypal.calls(r"/v2/payments/authorizations/[^/]+/void") == []
    assert all(row["authorized_at"] <= clock.now for row in table(client, pledges))


def test_the_settlement_pass_waits_for_a_hold_in_flight_and_releases_one_placed_after_the_deadline(world):
    client, paypal, clock = world["client"], world["paypal"], world["clock"]
    campaign_id = start(world, days=1)
    for _ in range(3):
        pledge(client, campaign_id)
    fourth = client.post(f"/api/campaigns/{campaign_id}/pledges").json()["order_id"]
    held, settled = race(
        client, ("POST", f"/api/campaigns/{campaign_id}/pledges/{fourth}/authorize"),
        ("POST", "/api/cron/settle", {"x-cron-secret": CRON_SECRET}), paused="authorize_order",
        meanwhile=lambda: clock.advance(days=1, minutes=1),  # the deadline passes while PayPal places the hold
    )
    assert held.status_code == 409 and "nothing will be charged" in held.json()["detail"], held.text
    assert settled.json() == {"settled": [{"id": campaign_id, "status": "collected"}],
                              "payouts": [{"id": campaign_id, "status": "pending"}]}
    late = by_order(client)[fourth]
    assert late["status"] == "voided" and paypal.authorizations[late["authorization_id"]]["status"] == "VOIDED"
    assert [row["status"] for order, row in by_order(client).items() if order != fourth] == ["captured"] * 3
    assert len(paypal.calls(r"/v2/payments/authorizations/[^/]+/capture")) == 3
    assert paypal.body(paypal.calls("/v1/payments/payouts")[0])["items"][0]["amount"]["value"] == "70.92"
    assert table(client, campaigns)[0]["report"] == []


def test_a_withdrawal_during_the_settlement_pass_waits_for_it_and_finds_the_campaign_closed(world):
    client, paypal, clock = world["client"], world["paypal"], world["clock"]
    campaign_id = start(world, days=1)
    orders = [pledge(client, campaign_id) for _ in range(3)]
    clock.advance(days=1, minutes=1)
    settled, withdrawn = race(
        client, ("POST", "/api/cron/settle", {"x-cron-secret": CRON_SECRET}),
        ("POST", f"/api/campaigns/{campaign_id}/pledges/{orders[0]}/withdraw"), paused="capture_authorization",
    )
    assert settled.json()["settled"] == [{"id": campaign_id, "status": "collected"}]
    assert withdrawn.status_code == 409 and "closed" in withdrawn.json()["detail"]
    assert [by_order(client)[order]["status"] for order in orders] == ["captured"] * 3
    assert paypal.calls(r"/v2/payments/authorizations/[^/]+/void") == []


def test_a_batch_paypal_processed_is_read_back_for_its_item(world):
    client, paypal = world["client"], world["paypal"]
    campaign_id = start(world)
    for _ in range(3):
        pledge(client, campaign_id)
    client.post(f"/api/campaigns/{campaign_id}/close")
    batch_id = table(client, payouts)[0]["batch_id"]
    paypal.finish_payout(batch_id, "UNCLAIMED")  # the batch is done, but the owner has not claimed the money yet
    header = {"batch_header": {"payout_batch_id": batch_id, "batch_status": "SUCCESS"}}
    assert webhook(client, "WH-BATCH", "PAYMENT.PAYOUTSBATCH.SUCCESS", header).json() == {"status": "ok"}
    assert paypal.calls(f"/v1/payments/payouts/{batch_id}", method="GET")
    assert table(client, payouts)[0]["status"] == "pending" and table(client, payouts)[0]["paypal_status"] == "UNCLAIMED"
    claimed = paypal.finish_payout(batch_id, "SUCCESS")
    assert webhook(client, "WH-ITEM", "PAYMENT.PAYOUTS-ITEM.SUCCEEDED", claimed).json() == {"status": "ok"}
    assert client.get(f"/api/campaigns/{campaign_id}").json()["owner"]["payout"]["status"] == "paid"
    # Once paid, later news changes nothing.
    assert webhook(client, "WH-LATE", "PAYMENT.PAYOUTSBATCH.DENIED", header).json() == {"status": "ok"}
    assert table(client, payouts)[0]["status"] == "paid"
