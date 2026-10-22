"""Real PayPal sandbox check of the money flows Walk-in uses, approved by the sandbox buyer in a real browser:
a kit purchase (create → approve → capture → refund) and two pledges (create → approve → authorize, then one voided and
one captured and refunded). Prints statuses only, never secrets."""
import asyncio
import re
import sys
import uuid
from pathlib import Path

import httpx
from playwright.async_api import Page, async_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.payments import paypal as pp  # noqa: E402

RETURN = "https://example.com/walkin-return"
CANCEL = "https://example.com/walkin-cancel"
SHOTS = ROOT / ".data" / "sandbox-shots"
ENV = dict(line.split("=", 1) for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines() if "=" in line and not line.startswith("#"))
BUYER, PASSWORD = ENV["PAYPAL_SANDBOX_BUYER_EMAIL"].strip(), ENV["PAYPAL_SANDBOX_BUYER_PASSWORD"].strip()
BUTTON = re.compile(r"^(Next|Log In|Pay Now|Pay|Continue|Complete Purchase|Agree & Continue|Continue to Review Order)$", re.I)


async def quiet(page: Page) -> None:
    """Waits for PayPal's page to settle: network idle and its lock-icon spinner gone."""
    for wait in (page.wait_for_load_state("networkidle", timeout=15000),
                 page.locator(".spinner, [aria-busy='true']").first.wait_for(state="hidden", timeout=15000)):
        try:
            await wait
        except Exception:
            pass


async def click(page: Page, selector_or_locator) -> bool:
    locator = page.locator(selector_or_locator) if isinstance(selector_or_locator, str) else selector_or_locator
    try:
        if await locator.first.is_visible():
            await locator.first.click(timeout=6000)
            return True
    except Exception:
        pass
    return False


async def approve(page: Page, url: str, label: str) -> None:
    """Logs in as the sandbox buyer if asked, then approves, until PayPal sends the browser back to RETURN."""
    SHOTS.mkdir(exist_ok=True)
    await page.goto(f"{url}&locale.x=en_US", wait_until="domcontentloaded")
    for step in range(20):
        if page.url.startswith(RETURN):
            print(f"  {label}: approved by the buyer")
            return
        await quiet(page)
        if page.url.startswith(RETURN):
            continue
        await page.screenshot(path=str(SHOTS / f"{label}-{step:02d}.png"))
        if await page.locator("#password").is_visible():
            if await page.locator("#email").is_visible() and not await page.locator("#email").input_value():
                await page.fill("#email", BUYER)
            await page.fill("#password", PASSWORD)
            await page.press("#password", "Enter")
            continue
        if await page.locator("#email").is_visible():
            await page.fill("#email", BUYER)
            await page.press("#email", "Enter")
            continue
        if await click(page, "#payment-submit-btn, [data-testid='submit-button-initial'], [data-id='payment-submit-btn']"):
            continue
        await click(page, page.get_by_role("button", name=BUTTON))
    await page.screenshot(path=str(SHOTS / f"{label}-final.png"), full_page=True)
    raise RuntimeError(f"{label}: not approved; ended at {page.url.split('?')[0]} (screenshots saved)")


async def main() -> None:
    assert "sandbox" in settings.paypal_api_base, "Refusing to run against a live PayPal account"
    run = uuid.uuid4().hex[:8]
    async with httpx.AsyncClient(timeout=40) as http, async_playwright() as playwright:
        client = pp.PayPalClient(settings.paypal_client_id, settings.paypal_client_secret, settings.paypal_api_base, http)
        browser = await playwright.chromium.launch(headless=True)
        page = await (await browser.new_context(locale="en-US")).new_page()

        print("Kit purchase ($19.00, CAPTURE)")
        custom = f"kit-test:{run}"
        order = await client.create_order(
            intent="CAPTURE", amount="19.00", currency="USD", description="Walk-in launch kit: sandbox test",
            custom_id=custom, request_id=f"test-kit-{run}", return_url=RETURN, cancel_url=CANCEL,
        )
        print(f"  created: {order['status']}")
        await approve(page, pp.approval_url(order), "kit")
        captured = await client.capture_order(order["id"], f"test-kit-capture-{run}")
        print(f"  captured: {captured['status']}, paid in full: {pp.paid_in_full(captured, '19.00', 'USD', custom)}")
        again = await client.capture_order(order["id"], f"test-kit-capture-{run}")
        print(f"  same capture again (idempotent request id): {again['status']}")
        capture_id = pp.summarize_capture(captured)["capture_id"]
        refund = await client.refund_capture(capture_id, f"test-kit-refund-{run}", note="Sandbox test refund")
        print(f"  refunded: {refund['status']}")

        for kind in ("void", "capture"):
            print(f"Pledge ($25.00, AUTHORIZE) then {kind}")
            custom = f"pledge-test:{run}:{kind}"
            order = await client.create_order(
                intent="AUTHORIZE", amount="25.00", currency="USD", description="Founding supporter: sandbox test",
                custom_id=custom, request_id=f"test-pledge-{kind}-{run}", return_url=RETURN, cancel_url=CANCEL,
            )
            await approve(page, pp.approval_url(order), f"pledge-{kind}")
            held = await client.authorize_order(order["id"], f"test-pledge-auth-{kind}-{run}")
            facts = pp.summarize_authorization(held)
            print(f"  authorized: {facts['authorization_status']}, in full: {pp.authorized_in_full(held, '25.00', 'USD', custom)}, "
                  f"expires: {facts['expiration_time']}")
            if kind == "void":
                voided = await client.void_authorization(facts["authorization_id"], f"test-void-{run}")
                status = (voided or {}).get("status") or (await client.get_authorization(facts["authorization_id"]))["status"]
                print(f"  voided: {status}")
            else:
                capture = await client.capture_authorization(facts["authorization_id"], f"test-cap-{run}")
                print(f"  captured: {capture['status']}")
                refund = await client.refund_capture(capture["id"], f"test-cap-refund-{run}")
                print(f"  refunded: {refund['status']}")
        await browser.close()


asyncio.run(main())
