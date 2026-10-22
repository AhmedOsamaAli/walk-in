"""Pledge campaigns: terms, progress, what to do with each hold, settlement with a fake PayPal, and the AI pitch."""
import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.answers import AnswerCache
from app.llm import LLM
from app.payments.paypal import PayPalClient, request_key
from app.payments.pledges import (
    Campaign,
    CampaignError,
    CampaignStatus,
    Pledge,
    PledgeStatus,
    accepting,
    decide,
    draft_offer,
    needs_reauthorization,
    new_campaign,
    pledge_from_order,
    progress,
    settle,
    validate_campaign,
)

API = "https://api-m.sandbox.paypal.com"
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
AUTHORIZED, CAPTURED, VOIDED, EXPIRED, FAILED = (
    PledgeStatus.AUTHORIZED, PledgeStatus.CAPTURED, PledgeStatus.VOIDED, PledgeStatus.EXPIRED, PledgeStatus.FAILED,
)


def campaign(**changes) -> Campaign:
    """A campaign of 3 supporters at $25 whose deadline passed five minutes ago."""
    return replace(Campaign(id="c1", amount="25.00", goal=3, deadline=NOW - timedelta(minutes=5)), **changes)


def pledge(n: int, days_ago: float = 1, **changes) -> Pledge:
    """Supporter n's pledge, held `days_ago` days before NOW."""
    at = NOW - timedelta(days=days_ago)
    fields = {
        "id": f"p{n}", "amount": "25.00", "status": AUTHORIZED, "order_id": f"ORDER{n}", "payer_id": f"PAYER{n}",
        "authorization_id": f"AUTH{n}", "authorized_at": at, "expires_at": at + timedelta(days=29),
    }
    return Pledge(**{**fields, **changes})


def kinds(actions) -> list[tuple]:
    return [(action.kind, action.pledge_id, action.reauthorize) for action in actions]


def test_new_campaigns_keep_to_the_allowed_terms():
    assert validate_campaign("25", 50, NOW + timedelta(days=21), NOW) == []
    assert validate_campaign("5.00", 3, NOW + timedelta(days=1), NOW) == []
    assert validate_campaign("200", 500, NOW + timedelta(days=29), NOW, "usd") == []
    made = new_campaign("c9", "25", 50, NOW + timedelta(days=21), NOW, "usd")
    assert (made.amount, made.currency, made.status, made.goal) == ("25.00", "USD", "open", 50)

    def problems(**changes) -> list[str]:
        terms = {"amount": "25", "goal": 50, "deadline": NOW + timedelta(days=21), "now": NOW, **changes}
        return validate_campaign(**terms)

    assert problems(amount="4.99") == ["The pledge must be from 5.00 to 200.00."]
    assert problems(amount="200.01") == ["The pledge must be from 5.00 to 200.00."]
    assert problems(amount=25.0) == ["The pledge must be from 5.00 to 200.00."]  # floats are not money
    assert problems(amount="twenty") == ["The pledge must be from 5.00 to 200.00."]
    assert problems(amount="25.005") == ["The pledge has more decimals than USD allows."]
    assert problems(goal=2) == problems(goal=501) == problems(goal=True) == ["The goal must be 3 to 500 supporters."]
    deadline = "The deadline must be 1 to 29 days away: PayPal holds a pledge for 29 days at most."
    assert problems(deadline=NOW + timedelta(hours=23)) == [deadline]
    assert problems(deadline=NOW + timedelta(days=29, minutes=1)) == [deadline]
    assert problems(deadline=datetime(2026, 12, 1)) == ["The deadline needs a date, a time and a time zone."]
    assert problems(currency="US") == ["The currency must be a three-letter code, such as USD."]
    with pytest.raises(CampaignError) as error:
        new_campaign("c9", "1", 1, NOW + timedelta(days=40), NOW)
    assert len(error.value.problems) == 3


def test_progress_counts_supporters_once_and_the_money_held_or_collected():
    pledges = [
        pledge(1), pledge(2, status=CAPTURED), replace(pledge(3), payer_id="PAYER1"),  # PAYER1 pledged twice
        pledge(4, status=VOIDED), Pledge("p5", "25.00"),  # released, and not approved yet
        pledge(6, days_ago=30, expires_at=NOW - timedelta(days=1)),  # a hold that ran out
    ]
    now = progress(campaign(goal=4), pledges, NOW)
    assert now["counts"] == {"created": 1, "authorized": 2, "declined": 0, "captured": 1, "voided": 1, "expired": 1,
                             "failed": 0}
    assert (now["pledges"], now["supporters"], now["total"], now["currency"]) == (3, 2, "75.00", "USD")
    assert (now["goal"], now["remaining"], now["percent"], now["funded"]) == (4, 2, 50, False)
    # Without a moment, a hold is counted as stored.
    assert progress(campaign(goal=3), pledges)["supporters"] == 3
    assert progress(campaign(goal=3), pledges)["funded"]


def test_pledges_are_read_from_paypal_s_authorized_order():
    order = {
        "id": "ORDER7", "status": "COMPLETED", "payer": {"payer_id": "PAYER7"},
        "purchase_units": [{"custom_id": "pledge:c1:p7", "payments": {"authorizations": [{
            "id": "AUTH7", "status": "CREATED", "amount": {"currency_code": "USD", "value": "25.00"},
            "create_time": "2026-11-01T09:30:00Z", "expiration_time": "2026-11-30T09:30:00Z",
        }]}}],
    }
    made = pledge_from_order("p7", order)
    assert made == Pledge(
        id="p7", amount="25.00", currency="USD", status=AUTHORIZED, order_id="ORDER7", payer_id="PAYER7",
        authorization_id="AUTH7", authorized_at=datetime(2026, 11, 1, 9, 30, tzinfo=UTC),
        expires_at=datetime(2026, 11, 30, 9, 30, tzinfo=UTC),
    )
    order["purchase_units"][0]["payments"]["authorizations"][0]["status"] = "DENIED"
    assert pledge_from_order("p7", order).status == PledgeStatus.DECLINED


def test_an_open_campaign_takes_pledges_and_only_marks_holds_that_ran_out():
    running = campaign(deadline=NOW + timedelta(days=3))
    card_hold = pledge(2, days_ago=8, expires_at=NOW - timedelta(hours=1))  # PayPal let this hold go early
    assert accepting(running, NOW) and not accepting(campaign(), NOW)
    assert not accepting(replace(running, closed_at=NOW - timedelta(minutes=1)), NOW)
    assert kinds(decide(running, [pledge(1), card_hold, Pledge("p3", "25.00")], NOW)) == [("expire", "p2", False)]
    assert decide(running, [pledge(1, days_ago=10)], NOW) == []  # funded or not, nothing moves before the deadline


def test_a_funded_campaign_captures_and_renews_holds_past_the_honor_period():
    renewed = pledge(3, days_ago=9, reauthorization_id="RE-AUTH3", reauthorized_at=NOW - timedelta(days=5))
    actions = decide(campaign(), [pledge(1, days_ago=1), pledge(2, days_ago=5), renewed], NOW)
    # p2 is past its 3-day honor period; p3 was renewed once already and PayPal allows no second renewal.
    assert kinds(actions) == [("capture", "p1", False), ("capture", "p2", True), ("capture", "p3", False)]
    assert needs_reauthorization(pledge(4, days_ago=3), NOW) and not needs_reauthorization(pledge(4, days_ago=2.9), NOW)
    assert needs_reauthorization(replace(pledge(4), authorized_at=None), NOW)  # unknown age: try, PayPal decides
    assert not needs_reauthorization(pledge(4, days_ago=30), NOW)  # past day 29 PayPal never renews a hold


def test_a_campaign_short_of_its_goal_releases_every_hold():
    pledges = [pledge(1), pledge(2), replace(pledge(3), payer_id="PAYER1")]  # 3 pledges, 2 supporters
    assert kinds(decide(campaign(), pledges, NOW)) == [("void", "p1", False), ("void", "p2", False), ("void", "p3", False)]
    early = campaign(deadline=NOW + timedelta(days=5), closed_at=NOW - timedelta(hours=1))
    assert [action.kind for action in decide(early, pledges, NOW)] == ["void"] * 3


def test_the_owner_can_close_a_funded_campaign_early():
    early = campaign(deadline=NOW + timedelta(days=5), closed_at=NOW - timedelta(hours=1))
    assert [action.kind for action in decide(early, [pledge(1), pledge(2), pledge(3)], NOW)] == ["capture"] * 3


def test_late_lapsed_and_leftover_holds():
    late = pledge(4, days_ago=0.001)  # held after the deadline passed
    lapsed = pledge(5, days_ago=20, expires_at=NOW - timedelta(days=1))  # ran out before the close
    actions = decide(campaign(), [pledge(1), pledge(2), pledge(3), late, lapsed], NOW)
    assert kinds(actions)[3:] == [("void", "p4", False), ("expire", "p5", False)]
    # Settled campaigns release whatever is still held; partial ones keep collecting, below the goal or not.
    assert kinds(decide(campaign(status=CampaignStatus.COLLECTED), [pledge(1)], NOW)) == [("void", "p1", False)]
    assert kinds(decide(campaign(status=CampaignStatus.EXPIRED), [pledge(1)], NOW)) == [("void", "p1", False)]
    assert kinds(decide(campaign(status=CampaignStatus.PARTIAL), [pledge(1)], NOW)) == [("capture", "p1", False)]
    # Money already collected means the campaign collects, even if the goal now looks out of reach.
    assert kinds(decide(campaign(), [pledge(1, status=CAPTURED), pledge(2)], NOW)) == [("capture", "p2", False)]


def paypal_error(status: int, issue: str, name: str = "UNPROCESSABLE_ENTITY") -> httpx.Response:
    return httpx.Response(status, json={"name": name, "message": "The requested action could not be performed.",
                                        "debug_id": "dbg1", "details": [{"issue": issue, "description": issue}]})


class FakePayPal:
    """A small PayPal: tokens, reauthorize, capture, void and orders. Each (operation, authorization) can be given
    replies to send first; otherwise every call succeeds."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.replies: dict[tuple[str, str], list[httpx.Response]] = {}
        self.orders: dict[str, dict] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        parts = request.url.path.strip("/").split("/")
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "token", "token_type": "Bearer", "expires_in": 32400})
        if parts[:2] == ["v2", "checkout"]:
            return httpx.Response(200, json=self.orders[parts[3]])
        authorization, operation = parts[3], parts[4]
        queued = self.replies.get((operation, authorization))
        if queued:
            return queued.pop(0)
        if operation == "reauthorize":
            return httpx.Response(201, json={"id": f"RE-{authorization}", "status": "CREATED"})
        if operation == "capture":
            return httpx.Response(201, json={
                "id": f"CAP-{authorization}", "status": "COMPLETED", "final_capture": True,
                "amount": json.loads(request.content)["amount"],
                "links": [{"rel": "up", "href": f"{API}/v2/payments/authorizations/{authorization}"}],
            })
        return httpx.Response(200, json={"id": authorization, "status": "VOIDED"})

    def calls(self) -> list[str]:
        """The payment calls made, as 'operation AUTHORIZATION', in a stable order."""
        paths = [r.url.path.split("/") for r in self.requests if r.url.path.startswith("/v2/payments/")]
        return sorted(f"{path[5]} {path[4]}" for path in paths)

    def request(self, operation: str, authorization: str) -> httpx.Request:
        return next(r for r in self.requests if r.url.path == f"/v2/payments/authorizations/{authorization}/{operation}")


def settle_with(fake: FakePayPal, the_campaign: Campaign, pledges: list[Pledge], now: datetime = NOW):
    client = PayPalClient("id", "secret", API, retries=0,
                          http_client=httpx.AsyncClient(transport=httpx.MockTransport(fake)))
    return asyncio.run(settle(the_campaign, pledges, client, now))


def by_id(result) -> dict:
    return {item.id: item for item in result.pledges}


def test_a_funded_campaign_collects_every_hold():
    fake = FakePayPal()
    result = settle_with(fake, campaign(), [pledge(1), pledge(2, days_ago=2), pledge(3, days_ago=2.5)])
    assert result.campaign.status == CampaignStatus.COLLECTED and result.reasons == []
    assert [(p.status, p.capture_id, p.error) for p in result.pledges] == [
        (CAPTURED, f"CAP-AUTH{n}", None) for n in (1, 2, 3)]
    assert fake.calls() == ["capture AUTH1", "capture AUTH2", "capture AUTH3"]
    capture = fake.request("capture", "AUTH1")
    assert json.loads(capture.content) == {"final_capture": True, "amount": {"currency_code": "USD", "value": "25.00"}}
    assert capture.headers["paypal-request-id"] == request_key("capture", "AUTH1")
    assert (result.progress["funded"], result.progress["total"], result.progress["counts"]["captured"]) == (True, "75.00", 3)


def test_holds_past_the_honor_period_are_renewed_once_and_the_renewal_is_captured():
    fake = FakePayPal()
    renewed = pledge(3, days_ago=9, reauthorization_id="RE-OLD3", reauthorized_at=NOW - timedelta(days=5))
    result = settle_with(fake, campaign(), [pledge(1, days_ago=5), pledge(2), renewed])
    assert fake.calls() == ["capture AUTH2", "capture RE-AUTH1", "capture RE-OLD3", "reauthorize AUTH1"]
    reauthorize = fake.request("reauthorize", "AUTH1")
    assert json.loads(reauthorize.content) == {"amount": {"currency_code": "USD", "value": "25.00"}}
    assert reauthorize.headers["paypal-request-id"] == request_key("reauthorize", "AUTH1")
    first = by_id(result)["p1"]
    assert (first.status, first.reauthorization_id, first.reauthorized_at, first.capture_id) == (
        CAPTURED, "RE-AUTH1", NOW, "CAP-RE-AUTH1")
    assert [outcome.reauthorized for outcome in result.outcomes] == [True, False, False]
    assert result.campaign.status == CampaignStatus.COLLECTED


def test_a_renewal_paypal_refuses_falls_back_to_capturing_the_hold_as_it_is():
    fake = FakePayPal()
    fake.replies[("reauthorize", "AUTH1")] = [paypal_error(422, "REAUTHORIZATION_TOO_SOON")]
    result = settle_with(fake, campaign(), [pledge(1, days_ago=3.01), pledge(2), pledge(3)])
    assert "capture AUTH1" in fake.calls() and by_id(result)["p1"].reauthorization_id is None
    assert by_id(result)["p1"].status == CAPTURED and result.campaign.status == CampaignStatus.COLLECTED


def test_already_captured_holds_count_as_collected():
    fake = FakePayPal()
    fake.replies[("capture", "AUTH2")] = [paypal_error(422, "AUTHORIZATION_ALREADY_CAPTURED")]
    fake.orders["ORDER2"] = {"id": "ORDER2", "status": "COMPLETED", "purchase_units": [{"payments": {"captures": [
        {"id": "CAP-EARLIER", "status": "COMPLETED",
         "links": [{"rel": "up", "href": f"{API}/v2/payments/authorizations/AUTH2"}]},
    ]}}]}
    result = settle_with(fake, campaign(), [pledge(1), pledge(2), pledge(3)])
    assert (by_id(result)["p2"].status, by_id(result)["p2"].capture_id) == (CAPTURED, "CAP-EARLIER")
    assert result.campaign.status == CampaignStatus.COLLECTED and result.reasons == []


def test_settling_again_sends_the_same_request_ids():
    first, second = FakePayPal(), FakePayPal()
    pledges = [pledge(1, days_ago=4), pledge(2), pledge(3)]
    settle_with(first, campaign(), pledges)
    settle_with(second, campaign(), pledges)  # as after a crash before the results were stored
    ids = [[(r.url.path, r.headers["paypal-request-id"]) for r in fake.requests if "payments" in r.url.path]
           for fake in (first, second)]
    assert sorted(ids[0]) == sorted(ids[1]) and len(ids[0]) == 4


def test_partial_failures_are_reported_and_retried():
    fake = FakePayPal()
    fake.replies[("capture", "AUTH2")] = [paypal_error(422, "INSTRUMENT_DECLINED")]
    fake.replies[("capture", "AUTH3")] = [paypal_error(503, "SERVICE_UNAVAILABLE", "SERVICE_UNAVAILABLE")]
    first = settle_with(fake, campaign(), [pledge(1), pledge(2), pledge(3)])
    assert first.campaign.status == CampaignStatus.PARTIAL
    assert [(p.status, p.error) for p in first.pledges] == [
        (CAPTURED, None), (FAILED, "INSTRUMENT_DECLINED"), (AUTHORIZED, "SERVICE_UNAVAILABLE")]
    assert [outcome.temporary for outcome in first.outcomes] == [False, False, True]
    assert first.reasons == [
        "1 pledge could not be collected: the card or bank declined the payment (INSTRUMENT_DECLINED).",
        "1 pledge is not collected yet (SERVICE_UNAVAILABLE); the next settlement tries again.",
    ]
    again = settle_with(fake, first.campaign, first.pledges, NOW + timedelta(hours=1))
    assert [outcome.pledge_id for outcome in again.outcomes] == ["p3"]  # the declined pledge is not tried again
    assert by_id(again)["p3"].status == CAPTURED and by_id(again)["p3"].error is None
    assert again.campaign.status == CampaignStatus.PARTIAL and len(again.reasons) == 1


def test_paypal_s_answers_decide_each_pledge():
    fake = FakePayPal()
    fake.replies[("capture", "AUTH1")] = [httpx.Response(201, json={
        "id": "CAP-P", "status": "PENDING", "status_details": {"reason": "PENDING_REVIEW"}})]
    fake.replies[("capture", "AUTH2")] = [httpx.Response(201, json={"id": "CAP-D", "status": "DECLINED"})]
    fake.replies[("reauthorize", "AUTH3")] = [paypal_error(422, "AUTHORIZATION_VOIDED")]
    fake.replies[("capture", "AUTH4")] = [paypal_error(401, "INVALID_TOKEN", "AUTHENTICATION_FAILURE")] * 2
    result = settle_with(fake, campaign(goal=4), [pledge(1), pledge(2), pledge(3, days_ago=5), pledge(4)])
    assert [(p.status, p.error) for p in result.pledges] == [
        (CAPTURED, None), (FAILED, "DECLINED"), (FAILED, "AUTHORIZATION_VOIDED"), (AUTHORIZED, "INVALID_TOKEN")]
    assert "capture AUTH3" not in fake.calls()  # a cancelled hold is never captured
    assert result.outcomes[0].capture_status == "PENDING" and result.outcomes[3].temporary
    assert result.campaign.status == CampaignStatus.PARTIAL
    assert result.reasons == [
        "1 pledge could not be collected: the hold had been cancelled (AUTHORIZATION_VOIDED).",
        "1 pledge could not be collected: PayPal declined the capture (DECLINED).",
        "1 pledge is not collected yet (INVALID_TOKEN); the next settlement tries again.",
        "1 payment is pending at PayPal, which completes or denies it later.",
    ]


def test_a_retry_that_succeeds_completes_the_collection():
    fake = FakePayPal()
    fake.replies[("capture", "AUTH3")] = [httpx.Response(429, json={"name": "RATE_LIMIT_REACHED", "message": "Too many requests."})]
    first = settle_with(fake, campaign(), [pledge(1), pledge(2), pledge(3)])
    assert first.campaign.status == CampaignStatus.PARTIAL
    again = settle_with(fake, first.campaign, first.pledges, NOW + timedelta(minutes=30))
    assert again.campaign.status == CampaignStatus.COLLECTED and again.reasons == []
    final = settle_with(fake, again.campaign, again.pledges, NOW + timedelta(hours=1))
    assert final.outcomes == [] and final.campaign.status == CampaignStatus.COLLECTED


def test_a_campaign_short_of_its_goal_releases_every_hold_once():
    fake = FakePayPal()
    fake.replies[("void", "AUTH2")] = [paypal_error(422, "PREVIOUSLY_VOIDED")]
    result = settle_with(fake, campaign(), [pledge(1), pledge(2)])
    assert result.campaign.status == CampaignStatus.EXPIRED and result.reasons == []
    assert [p.status for p in result.pledges] == [VOIDED, VOIDED]
    void = fake.request("void", "AUTH1")
    assert void.content == b"" and void.headers["paypal-request-id"] == request_key("void", "AUTH1")
    cancelled = campaign(deadline=NOW + timedelta(days=4), closed_at=NOW - timedelta(minutes=1))
    assert settle_with(FakePayPal(), cancelled, [pledge(1)]).campaign.status == CampaignStatus.CANCELLED


def test_a_void_goes_to_the_original_hold_and_flags_money_to_refund():
    fake = FakePayPal()
    fake.replies[("void", "AUTH2")] = [paypal_error(422, "PREVIOUSLY_CAPTURED")]
    fake.replies[("void", "AUTH3")] = [paypal_error(422, "AUTHORIZATION_EXPIRED")]
    fake.orders["ORDER2"] = {"purchase_units": [{"payments": {"captures": [{"id": "CAP-STRAY"}]}}]}
    renewed = pledge(1, reauthorization_id="RE-AUTH1")
    result = settle_with(fake, campaign(goal=5), [renewed, pledge(2), pledge(3)])
    assert fake.calls() == ["void AUTH1", "void AUTH2", "void AUTH3"]  # never the reauthorization
    assert [p.status for p in result.pledges] == [VOIDED, CAPTURED, EXPIRED]
    assert result.campaign.status == CampaignStatus.EXPIRED
    assert result.reasons == [
        "1 pledge was collected although the campaign fell short of its goal: refund it (CAP-STRAY)."]


def test_holds_that_ran_out_are_marked_without_calling_paypal():
    fake = FakePayPal()
    running = campaign(deadline=NOW + timedelta(days=2))
    lapsed = pledge(2, days_ago=10, expires_at=NOW - timedelta(minutes=1))
    result = settle_with(fake, running, [pledge(1), lapsed])
    assert fake.requests == [] and [p.status for p in result.pledges] == [AUTHORIZED, EXPIRED]
    assert result.campaign.status == CampaignStatus.OPEN and result.reasons == []


def test_a_late_hold_is_released_and_a_broken_pledge_does_not_stop_the_rest():
    fake = FakePayPal()
    broken = replace(pledge(3), amount="not money")
    late = pledge(4, days_ago=0.001)
    result = settle_with(fake, campaign(), [pledge(1), pledge(2), broken, late])
    assert [p.status for p in result.pledges] == [CAPTURED, CAPTURED, AUTHORIZED, VOIDED]
    assert by_id(result)["p3"].error == "ValueError" and result.campaign.status == CampaignStatus.PARTIAL
    assert "void AUTH4" in fake.calls()


DESIGN = {
    "name": "Golden Hour",
    "tagline": "Morning pastries for the block",
    "concept_statement": "A bakery for the morning crowd, with bread baked on site.",
    "offer": ["Kouign amann", "Rye loaf", "Cardamom bun"],
    "interior": {"mood": "warm and bright", "materials": ["oak"]},
    "hours": "Daily 7 am–3 pm",
    "partners": [{"name": "Corner Cellar", "why": "Drinks after dinner"}],
    "price_anchors": [{"name": "Crumb Bakehouse", "url": "https://crumb.example/", "level": 3}],
    "music": {"direction": "Local", "artists": ["Mobley", "Gary Clark Jr."]},
    "experience": {"soundtrack": [{"id": "a1", "name": "Mobley"}], "basis": "What people within 1.5 km over-index on."},
    "launch": {
        "audience": {"crowd": [{"label": "Families", "places": 3, "of": 3}], "artists": ["Mobley"],
                     "podcasts": ["Stassi"], "screen": [], "brands": ["Patagonia"], "shared": []},
        "where": {"minutes": 10, "reach_m": 556, "neighborhoods": ["Holly", "East Cesar Chavez"],
                  "sites_like": [{"name": "Sunrise Loaves", "url": "https://sunrise.example/"}]},
        "when": {"times": [{"label": "Morning", "places": 3, "of": 3}],
                 "intents": [{"label": "Routine visit", "places": 2, "of": 3, "angle": "Lead with the habit."}]},
        "claims": [
            {"kind": "only", "line": "The only $$$ bakery within a 10-minute walk",
             "proof": "None of the 2 bakeries inside the walk that list a price is $$$; 2 of the bakeries locals love are."},
            {"kind": "promise", "line": "Book ahead, or be served fast at the counter",
             "proof": "Reviews of 2 of the bakeries inside the walk flag long waits."},
        ],
    },
}
CONCEPT = {
    "name": "Golden Hour", "genre": "Bakery", "signature": ["Kouign amann", "Rye loaf"],
    "inspired_by": ["Crumb Bakehouse", "Sunrise Loaves"],
    "why_here": ["Locals travel a median 2.1 km to bakeries such as Crumb Bakehouse.",
                 "Neighbors rank bakery #6 among the place types they engage with."],
}
TERMS = {"amount": "25", "goal": 40, "deadline": datetime(2026, 11, 12, 23, 0, tzinfo=UTC)}
FORBIDDEN = ("Mobley", "Gary Clark", "Patagonia", "Stassi", "Crumb", "Sunrise Loaves", "Corner Cellar")


def llm_answering(draft: dict | None, seen: list[dict], status: int = 200) -> LLM:
    """The app's LLM client, answered by a fake OpenAI-compatible endpoint."""
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "overloaded"}})
        message = {"role": "assistant", "content": json.dumps(draft)}
        return httpx.Response(200, json={
            "id": "chatcmpl-1", "object": "chat.completion", "created": 0, "model": "test-model",
            "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
        })

    return LLM("key", "https://llm.test/v1/", "test-model", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def draft(llm, **extra) -> dict:
    return asyncio.run(draft_offer(llm, DESIGN, **{**TERMS, **extra}))


GOOD = {
    "title": "Bring Golden Hour to Holly",
    "pitch": "Golden Hour is the only $$$ bakery within a 10-minute walk, made for families' mornings. "
             "Join the 40 founding supporters it needs by November 12.",
    "perks": ["Your name on the founders' wall", "An invitation to the opening", "First taste of the kouign amann"],
}


def test_the_model_writes_the_words_and_the_owner_s_terms_stay_fixed():
    seen: list[dict] = []
    offer = draft(llm_answering(GOOD, seen), concept=CONCEPT)
    assert {key: offer[key] for key in ("title", "pitch", "perks")} == GOOD
    assert (offer["mode"], offer["model"], offer["rejected"]) == ("agent", "test-model", [])
    assert offer["how_it_works"] == (
        "Pledge $25.00. PayPal only holds it: it is collected if 40 supporters pledge by November 12, and released if "
        "not, so nobody pays unless the goal is met.")
    sent = seen[0]["messages"][1]["content"]
    brief = json.loads(sent)
    assert brief["owner_terms"] == {"pledge": "$25.00", "supporters_needed": 40, "deadline": "November 12, 2026"}
    assert brief["evidence"] == [
        {"claim": "The only $$$ bakery within a 10-minute walk",
         "proof": "None of the 2 bakeries inside the walk that list a price is $$$; 2 of the bakeries locals love are."},
        {"fact": "Neighbors rank bakery #6 among the place types they engage with."},
    ]
    assert brief["who"] == {"crowd": ["Families"], "times": ["Morning"], "reasons_to_visit": ["Routine visit"]}
    assert "Book ahead" not in sent  # a promise is the owner's to make
    assert not [name for name in FORBIDDEN if name in sent]  # the model never sees a real name to repeat


def test_lines_that_break_the_rules_are_replaced_by_the_evidence_rules():
    seen: list[dict] = []
    offer = draft(llm_answering({
        "title": "Golden Hour, for Patagonia fans",
        "pitch": "Join 99 neighbors and get 20% off your first coffee at Golden Hour.",
        "perks": ["A free coffee every week", "Your name on the founders' wall", "Front-row seats to Mobley",
                  "Order at goldenhour.com first", "Your name on the founders' wall"],
    }, seen))
    assert offer["title"] == "Be a founding supporter of Golden Hour"
    assert offer["pitch"] == ("Morning pastries for the block. The only $$$ bakery within a 10-minute walk. "
                              "Be one of the 40 founding supporters it needs by November 12.")
    assert offer["perks"] == ["Your name on the founders' wall"]  # the model's one good perk, once
    assert offer["mode"] == "agent"
    assert offer["rejected"] == [
        {"field": "title", "reason": "names Patagonia"},
        {"field": "pitch", "reason": "states 99, a number the inputs do not have"},
        {"field": "perks", "reason": "promises a discount the owner did not set"},
        {"field": "perks", "reason": "names Mobley"},
        {"field": "perks", "reason": "has a link"},
    ]


def test_without_a_model_the_evidence_rules_write_the_whole_pitch():
    offer = draft(None)
    assert offer == {
        "title": "Be a founding supporter of Golden Hour",
        "pitch": "Morning pastries for the block. The only $$$ bakery within a 10-minute walk. "
                 "Be one of the 40 founding supporters it needs by November 12.",
        "perks": ["Your name on the founding supporters' wall", "An invitation to the opening night",
                  "A first taste of Kouign amann"],
        "how_it_works": "Pledge $25.00. PayPal only holds it: it is collected if 40 supporters pledge by November 12, "
                        "and released if not, so nobody pays unless the goal is met.",
        "mode": "rules", "model": None, "rejected": [],
    }
    assert draft(LLM("", None, "no-key"))["mode"] == "rules"  # a model without a key is no model
    unnamed = asyncio.run(draft_offer(None, {"name": "Golden Hour", "launch": {}}, **TERMS))
    assert unnamed["pitch"] == ("Golden Hour is planned for a storefront near you. "
                                "Be one of the 40 founding supporters it needs by November 12.")


def test_an_ai_outage_or_an_empty_answer_falls_back_to_the_rules():
    assert draft(llm_answering(None, [], status=503))["mode"] == "rules"
    empty = draft(llm_answering({}, []))
    assert (empty["mode"], empty["rejected"]) == ("rules", [])
    junk = draft(llm_answering({"title": "", "pitch": 42, "perks": "free stuff"}, []))
    assert junk["mode"] == "rules" and [r["field"] for r in junk["rejected"]] == ["title", "pitch"]


def test_the_owner_s_discount_leads_the_perks_and_bounds_the_model():
    seen: list[dict] = []
    offer = draft(llm_answering({
        "title": "Founding supporters of Golden Hour",
        "pitch": "Founding supporters get 10% off every visit in the first year.",
        "perks": ["15% off for founders", "10% off your first year", "A first taste of the rye loaf"],
    }, seen), discount="10% off every visit in the first year")
    assert offer["pitch"] == "Founding supporters get 10% off every visit in the first year."
    assert offer["perks"] == ["10% off every visit in the first year", "A first taste of the rye loaf"]
    assert offer["rejected"] == [{"field": "perks", "reason": "states 15, a number the inputs do not have"}]
    assert json.loads(seen[0]["messages"][1]["content"])["owner_terms"]["discount"] == "10% off every visit in the first year"
    assert draft(None, discount="10% off every visit in the first year")["perks"][0] == "10% off every visit in the first year"


def test_a_long_pitch_keeps_its_first_whole_sentences_and_avoid_adds_names():
    long_pitch = ("Golden Hour bakes for Holly. Pledge with your neighbors by November 12. " + "Mornings matter. " * 20).strip()
    offer = draft(llm_answering({**GOOD, "pitch": long_pitch}, []))
    assert offer["pitch"].startswith("Golden Hour bakes for Holly. Pledge with your neighbors by November 12.")
    assert len(offer["pitch"]) <= 300 and offer["rejected"] == []
    named = draft(llm_answering({**GOOD, "pitch": "Closer than Joe's Bakery & Co, and open early."}, []),
                  avoid=["Joe's Bakery & Co"])
    assert named["rejected"] == [{"field": "pitch", "reason": "names Joe's Bakery & Co"}]


def test_drafts_for_the_same_evidence_are_replayed(tmp_path):
    seen: list[dict] = []
    answers = AnswerCache(tmp_path)
    llm = llm_answering(GOOD, seen)
    first = asyncio.run(draft_offer(llm, DESIGN, answers=answers, **TERMS))
    again = asyncio.run(draft_offer(llm, DESIGN, answers=answers, **TERMS))
    assert first == again and len(seen) == 1
