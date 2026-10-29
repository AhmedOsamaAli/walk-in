"""End-to-end check of Walk-in Founders against a running server and PayPal's sandbox, as people would use it: the owner
signs in (development login) and starts a campaign from a ready launch kit; each sandbox buyer pledges with the redirect
flow, approves in PayPal (headless Chromium, locale en_US) and comes back to the campaign's page, which holds the
pledge; one extra pledge is withdrawn; the owner closes the campaign once funded, it settles, and the owner is paid out.
Prints each step's status, never secrets.

    python docs/founders/e2e_campaign.py [--server http://127.0.0.1:8780] [--kit KIT_TOKEN] [--amount 5.00]

Start the server first, from the repository's root, with the development login and its own address:

    $env:AUTH_DEV_LOGIN="true"; $env:PUBLIC_URL="http://127.0.0.1:8780"; python -m uvicorn app.main:app --port 8780

Needs in .env: the sandbox app's PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET (a US business account), three US personal
sandbox buyers (PAYPAL_SANDBOX_BUYERS="email:password;email:password;email:password", or PAYPAL_SANDBOX_BUYER_EMAIL and
PAYPAL_SANDBOX_BUYER_PASSWORD with _2 and _3 siblings: a goal counts distinct PayPal accounts, at least 3), CRON_SECRET
(to run the settlement pass the scheduler would), and optionally PAYPAL_SANDBOX_PAYOUT_EMAIL (the owner's PayPal email,
which receives the payout; the first buyer's by default). With fewer than three buyers the goal cannot be met: the
campaign is cancelled instead and every hold released. Run it with a Python that has httpx and playwright.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sandbox_money_flows import approve, buyers, env_file  # noqa: E402

ZAMALEK_KIT = "Uv6RpsfnBAa0kIfOdIEEVukHMeS9bqXG1imQEaiFuj4"


def step(label: str, response: httpx.Response, *keys: str) -> dict:
    try:
        body = response.json()
    except ValueError:
        body = {}
    shown = {key: body.get(key) for key in keys} if keys and isinstance(body, dict) else ""
    if response.status_code >= 400 and isinstance(body, dict):
        shown = {"detail": body.get("detail"), **({"problems": body["problems"]} if "problems" in body else {})}
    print(f"{label}: {response.status_code} {shown}")
    return body if isinstance(body, dict) else {}


async def find_kit(http: httpx.AsyncClient, given: str | None) -> str | None:
    """The kit to start from: the one given, else the first example's ready kit, else the Zamalek example's."""
    if given:
        return given
    for example in (await http.get("/api/examples")).json() or []:
        kit = example.get("kit") or {}
        if kit.get("token"):
            return kit["token"]
    page = await http.get(f"/api/kits/{ZAMALEK_KIT}")
    return ZAMALEK_KIT if page.status_code == 200 and page.json().get("status") == "ready" else None


async def run(server: str, kit_given: str | None, amount: str) -> int:
    from playwright.async_api import async_playwright

    env = env_file()
    found = buyers()
    run_id = uuid.uuid4().hex[:6]
    async with httpx.AsyncClient(base_url=server, timeout=90) as http:
        config = (await http.get("/api/config")).json()
        paypal = config.get("paypal") or {}
        print(f"config: PayPal enabled {paypal.get('enabled')}, {paypal.get('environment')}, dev login {config.get('dev_login')}")
        if not paypal.get("enabled") or paypal.get("environment") != "sandbox":
            print("The server must have PayPal configured, in the sandbox.")
            return 1
        if not config.get("dev_login"):
            print("Start the server with AUTH_DEV_LOGIN=true (and a PUBLIC_URL that is not https).")
            return 1
        if not found:
            print("Set the sandbox buyers in .env (see this script's docstring).")
            return 1
        step("owner signs in", await http.post("/api/auth/dev", json={"email": f"e2e-{run_id}@example.com", "name": "E2E Owner"}))
        kit = await find_kit(http, kit_given)
        if not kit:
            print("No ready launch kit found: pass --kit with a ready kit's token.")
            return 1
        print(f"kit: {kit[:6]}…")
        goal = 3
        deadline = (datetime.now(UTC) + timedelta(days=7)).isoformat()
        terms = {"kit_token": kit, "amount": amount, "goal": goal, "deadline": deadline, "perk": None}
        drafted = step("draft", await http.post("/api/campaigns/draft", json=terms), "title", "problems")
        if drafted.get("problems") or not drafted.get("title"):
            return 1
        payout_email = env.get("PAYPAL_SANDBOX_PAYOUT_EMAIL") or found[0][0]
        created = step("create", await http.post("/api/campaigns", json={
            **terms, "payout_email": payout_email, **{key: drafted[key] for key in ("title", "pitch", "perks")},
        }), "id", "url")
        campaign_id = created.get("id")
        if not campaign_id:
            return 1
        view = step("campaign", await http.get(f"/api/campaigns/{campaign_id}"), "status", "accepting", "evidence")
        print(f"  place: {view.get('place')}")

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                pledged = []
                for number, buyer in enumerate(found[:goal] + found[:1], 1):
                    async with httpx.AsyncClient(base_url=server, timeout=90) as supporter:  # no account, no cookie
                        order = step(f"supporter {number} pledges (redirect)", await supporter.post(
                            f"/api/campaigns/{campaign_id}/pledges", json={"flow": "redirect"}), "order_id")
                        if not order.get("approve_url"):
                            return 1
                        context = await browser.new_context(locale="en-US")
                        page = await context.new_page()
                        landed = await approve(page, order["approve_url"], f"e2e-{number}", buyer,
                                               back=f"{server.rstrip('/')}/p/{campaign_id}")
                        await context.close()
                        query = parse_qs(urlsplit(landed).query)
                        reference = (query.get("pledge") or query.get("token") or [order["order_id"]])[0]
                        print(f"  back on the campaign's page with pledge={reference[:6]}… and PayPal's token")
                        held = step(f"supporter {number} is held", await supporter.post(
                            f"/api/campaigns/{campaign_id}/pledges/{reference}/authorize"), "status", "progress")
                        pledged.append((order["order_id"], held.get("status")))
                if len(pledged) > goal:  # the extra pledge, from the first buyer again, is withdrawn
                    extra = pledged[-1][0]
                    async with httpx.AsyncClient(base_url=server, timeout=90) as supporter:
                        step("the extra pledge is withdrawn", await supporter.post(
                            f"/api/campaigns/{campaign_id}/pledges/{extra}/withdraw"), "status", "progress")
            finally:
                await browser.close()

        view = step("campaign", await http.get(f"/api/campaigns/{campaign_id}"), "progress")
        funded = (view.get("progress") or {}).get("funded")
        if funded:
            closed = step("owner closes early", await http.post(f"/api/campaigns/{campaign_id}/close"), "status", "accepting")
        else:
            print("The goal was not met (it needs three different sandbox buyers): cancelling instead.")
            closed = step("owner cancels", await http.post(f"/api/campaigns/{campaign_id}/cancel"), "status", "accepting")
        owner = closed.get("owner") or {}
        print(f"  counts: {owner.get('counts')}")
        print(f"  report: {owner.get('report')}")
        print(f"  payout: {owner.get('payout')}")
        secret = env.get("CRON_SECRET")
        deadline_s = time.monotonic() + 120
        while funded and secret and time.monotonic() < deadline_s:
            settled = step("settlement pass", await http.post("/api/cron/settle", headers={"X-Cron-Secret": secret}),
                           "settled", "payouts")
            payout = ((await http.get(f"/api/campaigns/{campaign_id}")).json().get("owner") or {}).get("payout") or {}
            print(f"  payout: {payout}")
            if payout.get("status") in ("paid", "failed") or not settled:
                break
            await asyncio.sleep(10)
        final = step("final campaign", await http.get(f"/api/campaigns/{campaign_id}"), "status", "progress")
        print(f"  owner: {final.get('owner')}")
        expected = "collected" if funded else "cancelled"
        return 0 if final.get("status") in (expected, "partial") else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--server", default="http://127.0.0.1:8780")
    parser.add_argument("--kit", default=None, help="a ready launch kit's token (default: an example's)")
    parser.add_argument("--amount", default="5.00", help="each pledge, 5.00 to 200.00")
    options = parser.parse_args()
    return asyncio.run(run(options.server.rstrip("/"), options.kit, options.amount))


if __name__ == "__main__":
    sys.exit(main())
