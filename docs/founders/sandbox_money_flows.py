"""Real PayPal sandbox check of the money flows Walk-in Founders uses, each approved by a sandbox buyer in headless
Chromium (locale en_US): a pledge held then released (AUTHORIZE, approve, authorize, void), a pledge held then collected
(a renewal PayPal refuses within the 3-day honor period, then capture and its net after PayPal's fee), a payout (sent,
sent again with the same request id, then a duplicate sender_batch_id leading back to it), and the capture refunded.
Prints statuses only, never secrets.

    python docs/founders/sandbox_money_flows.py

Needs in .env: PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET of a sandbox app whose business account can take payments (a
US business account), PAYPAL_SANDBOX_BUYER_EMAIL and PAYPAL_SANDBOX_BUYER_PASSWORD (a US personal sandbox account), and
optionally PAYPAL_SANDBOX_PAYOUT_EMAIL (who receives the test payout; the buyer by default). Run it with a Python that
has httpx and playwright (python -m playwright install chromium). Refuses a live PayPal account.
"""
from __future__ import annotations

import asyncio
import contextlib
import re
import sys
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.payments import paypal as pp  # noqa: E402

RETURN = "https://example.com/walkin-return"
CANCEL = "https://example.com/walkin-cancel"
SHOTS = ROOT / ".data" / "sandbox-shots"
BUTTON = re.compile(
    r"^(Next|Log In|Pay Now|Pay|Continue|Agree & Continue|Continue to Review Order|Complete Purchase|Save and Continue)$",
    re.IGNORECASE,
)


def env_file() -> dict[str, str]:
    """.env's values (the app's settings do not carry the sandbox buyer's)."""
    path = ROOT / ".env"
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def buyers() -> list[tuple[str, str]]:
    """The sandbox buyers: PAYPAL_SANDBOX_BUYERS ("email:password;email:password"), else PAYPAL_SANDBOX_BUYER_EMAIL and
    PAYPAL_SANDBOX_BUYER_PASSWORD with their _2 and _3 siblings."""
    env = env_file()
    found = []
    for pair in (env.get("PAYPAL_SANDBOX_BUYERS") or "").split(";"):
        if ":" in pair:
            email, password = pair.split(":", 1)
            found.append((email.strip(), password.strip()))
    for suffix in ("", "_2", "_3"):
        email, password = env.get(f"PAYPAL_SANDBOX_BUYER_EMAIL{suffix}"), env.get(f"PAYPAL_SANDBOX_BUYER_PASSWORD{suffix}")
        if email and password and (email, password) not in found:
            found.append((email, password))
    return found


async def quiet(page) -> None:
    """Waits for PayPal's page to settle: network idle and its spinner gone."""
    for wait in (page.wait_for_load_state("networkidle", timeout=15000),
                 page.locator(".spinner, [aria-busy='true']").first.wait_for(state="hidden", timeout=15000)):
        with contextlib.suppress(Exception):
            await wait


async def click(page, selector_or_locator) -> bool:
    locator = page.locator(selector_or_locator) if isinstance(selector_or_locator, str) else selector_or_locator
    try:
        if await locator.first.is_visible():
            await locator.first.click(timeout=6000)
            return True
    except Exception:
        pass
    return False


async def approve(page, url: str, label: str, buyer: tuple[str, str], back: str = RETURN) -> str:
    """Logs in as the sandbox buyer when asked and approves, until PayPal sends the browser to `back`; the address PayPal
    sent it to (before the page there changes it). Screenshots go to .data/sandbox-shots when it does not."""
    email, password = buyer
    SHOTS.mkdir(parents=True, exist_ok=True)
    landed: list[str] = []

    def arrived(frame) -> None:
        if frame == page.main_frame and frame.url.startswith(back):
            landed.append(frame.url)

    page.on("framenavigated", arrived)
    joiner = "&" if "?" in url else "?"
    await page.goto(f"{url}{joiner}locale.x=en_US", wait_until="domcontentloaded")
    for step in range(25):
        if landed or page.url.startswith(back):
            print(f"  {label}: approved by the sandbox buyer")
            return landed[0] if landed else page.url
        await quiet(page)
        if landed or page.url.startswith(back):
            continue
        await page.screenshot(path=str(SHOTS / f"{label}-{step:02d}.png"))
        if await page.locator("#password").is_visible():
            if await page.locator("#email").is_visible() and not await page.locator("#email").input_value():
                await page.fill("#email", email)
            await page.fill("#password", password)
            await page.press("#password", "Enter")
            continue
        if await page.locator("#email").is_visible():
            await page.fill("#email", email)
            await page.press("#email", "Enter")
            continue
        if await click(page, "#payment-submit-btn, [data-testid='submit-button-initial'], [data-id='payment-submit-btn']"):
            continue
        await click(page, page.get_by_role("button", name=BUTTON))
    await page.screenshot(path=str(SHOTS / f"{label}-final.png"), full_page=True)
    raise RuntimeError(f"{label}: not approved; ended at {page.url.split('?')[0]} (screenshots in .data/sandbox-shots)")


async def hold(client: pp.PayPalClient, page, run: str, kind: str, buyer: tuple[str, str]) -> tuple[dict, str]:
    """A $25.00 pledge, approved by the buyer and held: its authorization's facts and its custom_id."""
    custom = f"pledge-test-{run}-{kind}"
    order = await client.create_order(
        intent="AUTHORIZE", amount="25.00", currency="USD", description="Founding supporter: sandbox test",
        custom_id=custom, request_id=pp.request_key("test-order", run, kind), return_url=RETURN, cancel_url=CANCEL,
    )
    print(f"  order {order['status']}")
    await approve(page, pp.approval_url(order), f"pledge-{kind}", buyer)
    held = await client.authorize_order(order["id"], pp.request_key("test-authorize", run, kind))
    facts = pp.summarize_authorization(held)
    print(f"  authorized: {facts['authorization_status']}, in full: {pp.authorized_in_full(held, '25.00', 'USD', custom)}, "
          f"honor period ends {facts['honor_period_end']}, expires {facts['expiration_time']}")
    return facts, custom


async def main() -> int:
    from playwright.async_api import async_playwright

    if not settings.paypal_enabled:
        print("PayPal is not configured: set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in .env.")
        return 1
    if settings.paypal_environment != "sandbox":
        print("Refusing to run against a live PayPal account.")
        return 1
    found = buyers()
    if not found:
        print("Set PAYPAL_SANDBOX_BUYER_EMAIL and PAYPAL_SANDBOX_BUYER_PASSWORD (a US personal sandbox account) in .env.")
        return 1
    buyer = found[0]
    receiver = env_file().get("PAYPAL_SANDBOX_PAYOUT_EMAIL") or buyer[0]
    run = uuid.uuid4().hex[:8]
    failed = False
    async with httpx.AsyncClient(timeout=40) as http, async_playwright() as playwright:
        client = pp.PayPalClient(settings.paypal_client_id, settings.paypal_client_secret, settings.paypal_api_base, http)
        browser = await playwright.chromium.launch(headless=True)
        page = await (await browser.new_context(locale="en-US")).new_page()
        try:
            print("1. Pledge held, then released (the campaign fell short, or the supporter withdrew)")
            facts, _ = await hold(client, page, run, "void", buyer)
            await client.void_authorization(facts["authorization_id"], pp.request_key("test-void", run))
            print(f"  voided: {(await client.get_authorization(facts['authorization_id']))['status']}")

            print("2. Pledge held, then collected (the campaign met its goal)")
            facts, _ = await hold(client, page, run, "capture", buyer)
            try:
                await client.reauthorize_authorization(facts["authorization_id"], pp.request_key("test-reauth", run),
                                                       "25.00", currency="USD")
                print("  renewed within the honor period (PayPal allowed it)")
            except pp.PayPalError as exc:
                print(f"  renewal within the honor period refused, as expected: {exc.status} {(exc.issues or [exc.name])[0]}")
            capture = await client.capture_authorization(facts["authorization_id"], pp.request_key("test-capture", run),
                                                         "25.00", currency="USD")
            print(f"  captured: {capture.get('status')}, net after PayPal's fee: {pp.net_amount(capture)}")
            again = await client.capture_authorization(facts["authorization_id"], pp.request_key("test-capture", run),
                                                       "25.00", currency="USD")
            print(f"  the same capture again (same request id): {again.get('status')}, same id: {again.get('id') == capture.get('id')}")
            read = await client.get_capture(capture["id"])
            print(f"  capture read back: {read.get('status')}, net {pp.net_amount(read)}")

            print("3. Payout of $1.00 to the receiver, idempotent")
            sender = f"walkin-test-{run}"
            sent = await client.create_payout(
                sender_batch_id=sender, receiver=receiver, amount="1.00", currency="USD", note="Walk-in Founders sandbox test",
                email_subject="Walk-in Founders sandbox test", email_message="A sandbox test payout.",
                request_id=pp.request_key("test-payout", run),
            )
            facts = pp.summarize_payout(sent)
            print(f"  sent: batch {facts['batch_status']}")
            repeat = await client.create_payout(
                sender_batch_id=sender, receiver=receiver, amount="1.00", currency="USD", note="Walk-in Founders sandbox test",
                email_subject="Walk-in Founders sandbox test", email_message="A sandbox test payout.",
                request_id=pp.request_key("test-payout", run),
            )
            print(f"  sent again (same request id): same batch: {pp.summarize_payout(repeat)['payout_batch_id'] == facts['payout_batch_id']}")
            try:
                await client.create_payout(
                    sender_batch_id=sender, receiver=receiver, amount="1.00", currency="USD", note="duplicate",
                    email_subject="duplicate", email_message="duplicate", request_id=str(uuid.uuid4()),
                )
                print("  a new request with the same sender_batch_id was accepted (unexpected)")
                failed = True
            except pp.PayPalError as exc:
                original = pp.duplicate_payout(exc)
                print(f"  a new request with the same sender_batch_id: {exc.status} {exc.name}; "
                      f"leads back to the batch: {original == facts['payout_batch_id']}")
            for _ in range(6):
                batch = pp.summarize_payout(await client.get_payout_batch(facts["payout_batch_id"]))
                if batch["status"] != "pending":
                    break
                await asyncio.sleep(5)
            print(f"  payout now: {batch['batch_status']} / item {batch['item_status']} -> {batch['status']}")

            print("4. The capture refunded (cleanup)")
            refund = await client.refund_capture(capture["id"], pp.request_key("test-refund", run), note="Sandbox test refund")
            print(f"  refunded: {refund.get('status')}")
            print(f"Webhooks registered for this app: {len(await client.list_webhooks())}")
        except pp.PayPalError as exc:
            print(f"PayPal refused: {exc}")
            failed = True
        finally:
            await browser.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
