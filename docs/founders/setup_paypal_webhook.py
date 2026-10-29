"""One-off setup for Walk-in Founders: registers the PayPal webhook for a backend's address, writes its id to .env as
PAYPAL_WEBHOOK_ID, and adds a CRON_SECRET there if there is none. Prints no secret values.

    python docs/founders/setup_paypal_webhook.py https://walk-in-aoa2.onrender.com

The address is the backend's own (PayPal delivers to {address}/api/paypal/webhook, over HTTPS). A webhook already
registered for that address is reused, its event types brought up to date. Uses PAYPAL_CLIENT_ID and
PAYPAL_CLIENT_SECRET from .env, and refuses a live PayPal account: set the same PAYPAL_WEBHOOK_ID on the backend (Render's
environment), and the same CRON_SECRET there and in the repository's secrets for .github/workflows/settle.yml.
"""
from __future__ import annotations

import asyncio
import secrets
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.payments.paypal import WEBHOOK_EVENTS, PayPalClient, PayPalError  # noqa: E402

ENV = ROOT / ".env"


def set_env(key: str, value: str, replace: bool = True) -> bool:
    """Sets KEY=value in .env; with replace=False an existing value is kept. True when the file changed."""
    text = ENV.read_text(encoding="utf-8") if ENV.exists() else ""
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.split("=", 1)[0].strip() == key:
            current = line.split("=", 1)[1].strip() if "=" in line else ""
            if (current and not replace) or line == f"{key}={value}":
                return False
            lines[index] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    ENV.write_text(newline.join(lines) + newline, encoding="utf-8")
    return True


def masked(value: str) -> str:
    return f"{value[:4]}…{value[-4:]}" if len(value) > 8 else "…"


async def main(address: str) -> int:
    if not settings.paypal_enabled:
        print("PayPal is not configured: set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in .env first.")
        return 1
    if settings.paypal_environment != "sandbox":
        print("Refusing to touch a live PayPal account.")
        return 1
    url = address.rstrip("/") + "/api/paypal/webhook"
    if not url.startswith("https://"):
        print("PayPal only delivers webhooks to HTTPS addresses: give the backend's https:// address.")
        return 1
    async with httpx.AsyncClient(timeout=30) as http:
        client = PayPalClient(settings.paypal_client_id, settings.paypal_client_secret, settings.paypal_api_base, http)
        try:
            hooks = await client.list_webhooks()
            hook = next((item for item in hooks if str(item.get("url") or "").rstrip("/") == url), None)
            if hook is None:
                hook = await client.create_webhook(url)
                print(f"Created the webhook for {url}")
            else:
                have = {event.get("name") for event in hook.get("event_types") or []}
                if have != set(WEBHOOK_EVENTS):
                    hook = await client.update_webhook_events(hook["id"])
                    print(f"Reusing the webhook for {url}; its event types are brought up to date")
                else:
                    print(f"Reusing the webhook for {url}")
        except PayPalError as exc:
            print(f"PayPal refused: {exc}")
            return 1
    events = sorted(event.get("name") for event in hook.get("event_types") or [])
    print(f"Webhook id {masked(hook['id'])}, {len(events)} event types: {', '.join(events)}")
    print("PAYPAL_WEBHOOK_ID", "written to .env" if set_env("PAYPAL_WEBHOOK_ID", hook["id"]) else "already in .env")
    print("CRON_SECRET", "added to .env" if set_env("CRON_SECRET", secrets.token_urlsafe(32), replace=False)
          else "already in .env (kept)")
    print("Set the same PAYPAL_WEBHOOK_ID and CRON_SECRET on the backend, and BACKEND_URL and CRON_SECRET as the "
          "repository's secrets for .github/workflows/settle.yml.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(asyncio.run(main(sys.argv[1])))
