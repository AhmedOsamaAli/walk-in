"""One-off setup: the PayPal sandbox webhook for the hosted app, and a cron secret. Prints no secret values."""
import asyncio
import secrets
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.payments.paypal import PayPalClient  # noqa: E402

URL = "https://walk-in-aoa2.onrender.com/api/paypal/webhook"
ENV = ROOT / ".env"


def set_env(key: str, value: str, replace: bool = True) -> bool:
    """Sets KEY=value in .env; with replace=False an existing value is kept. True when the file changed."""
    text = ENV.read_text(encoding="utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.split("=", 1)[0].strip() == key:
            if not replace or line == f"{key}={value}":
                return False
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    ENV.write_text(newline.join(lines) + newline, encoding="utf-8")
    return True


async def main() -> None:
    assert settings.paypal_enabled, "PayPal is not configured in .env"
    assert "sandbox" in settings.paypal_api_base, "Refusing to touch a live PayPal account"
    async with httpx.AsyncClient(timeout=30) as http:
        client = PayPalClient(settings.paypal_client_id, settings.paypal_client_secret, settings.paypal_api_base, http)
        hooks = await client.list_webhooks()
        hook = next((h for h in hooks if h.get("url") == URL), None)
        if hook:
            print("Reusing the existing webhook")
        else:
            hook = await client.create_webhook(URL)
            print("Created the webhook")
        events = sorted(e.get("name") for e in hook.get("event_types") or [])
        print(f"id: {hook['id'][:4]}…{hook['id'][-4:]}  events: {len(events)}  {', '.join(events)}")
        print("PAYPAL_WEBHOOK_ID", "updated in .env" if set_env("PAYPAL_WEBHOOK_ID", hook["id"]) else "already in .env")
    changed = set_env("CRON_SECRET", secrets.token_urlsafe(32), replace=False)
    print("CRON_SECRET", "added to .env" if changed else "already in .env (kept)")


asyncio.run(main())
