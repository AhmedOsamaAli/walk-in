# Walk-in paid features: where they stand and how to continue

This repository is a snapshot of Walk-in taken on 2026-10-22, when its paid features were split off so the main
repository (`AhmedOsamaAli/walk-in`) could stay focused on the Qloo Agentic Hackathon. Continue here for the PayPal AI
Hackathon. Everything free in Walk-in (surveys, accounts, the Cloudflare front door) is also here; merge later
improvements from the main repository with `git remote add main https://github.com/AhmedOsamaAli/walk-in`.

## PayPal AI Hackathon

- Deadline: November 12, 2026, 12:00 PT. Judging: December 1–15 (the demo must stay live until December 15).
- Needs: a public repository, a working demo, a public YouTube video under 3 minutes, a text description and a
  statement of the AI tools used. Judging is a pass/fail fit check plus five equally weighted criteria.

## What is here

| Part | Files | State |
|---|---|---|
| PayPal REST client | `app/payments/paypal.py`, `tests/test_paypal.py` | Done and reviewed: CAPTURE and AUTHORIZE orders, captures, authorizations, reauthorize, void, refund, webhook verification on the raw body, idempotent request ids, token cache, retries. |
| Pledge rules | `app/payments/pledges.py`, `tests/test_pledges.py` | Done and reviewed: campaigns of at most 27 days (the 29-day hold minus a 2-day settlement margin); "funded at close" decided only from holds valid at the close and stored before the first capture (`decide_funding`, or `settle(..., record=...)`); the AI-drafted pitch with its checks (`draft_offer`, `offer_problems`). |
| Launch kit | `app/survey/kit.py`, `tests/test_kit.py` | Done and reviewed: ad copy per channel with per-field checks (names and possessives, prices, quantities, discounts, "only" claims), poster, tracked links, an untested-concept caution. |
| Dossier | `app/survey/dossier.py`, `tests/test_dossier.py` | Done and reviewed: 12 sections, each with its basis; one ordering for the rank and the alternatives; no model-written numbers. |
| Routes, stores, settlement | `app/sales.py` (the one seam into `app/main.py`), `app/commerce.py`, `app/settlement.py`, `app/routes/{kits,campaigns,hooks}.py`, `app/db/{kits,campaigns,events}.py`, `migrations/versions/0003_payments.py`, `.github/workflows/settle.yml` | Built to the contract and tested against a fake PayPal (`tests/test_commerce.py`, `tests/test_campaigns.py`). Never run against the real sandbox. |
| Web pages | `frontend/src/pages/{KitPage,DossierPage,PledgePage,PaymentPages}.tsx`, `frontend/src/components/kit/`, `KitOffer`, `PayPalPay`, `SandboxNotice`, `lib/{commerce,kit,poster}.ts`, `state/kit.ts`, `styles/payments.css` | Built and checked against a mocked API. Print styles for the dossier and the poster were never written. Never run against the real sandbox. |
| API contract | `docs/paid/commerce-api.md` | The agreed shape of every endpoint, cookie and page. Deviations: a funded campaign shows publicly as `partial` until collected; extra fields `pending`, `problems` and `url`. |

## The blocker found in testing: the sandbox seller's country

A real sandbox run (`docs/paid/sandbox_money_flows.py`) created a $19 order and the sandbox buyer approved it in a
browser, but the capture failed with `422 UNPROCESSABLE_ENTITY / COMPLIANCE_VIOLATION`: the sandbox business account
was created as Egyptian, and PayPal blocks captures for it. Fix (about 5 minutes, in the PayPal developer dashboard):

1. Sandbox → Accounts → Create account → Business, United States; and another → Personal, United States.
2. Apps & Credentials (Sandbox) → Create App ("Walk-in US", Merchant) on the new US business account.
3. In `.env`: the new app's `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET`, and the US personal account's
   `PAYPAL_SANDBOX_BUYER_EMAIL` / `PAYPAL_SANDBOX_BUYER_PASSWORD`.
4. Run `python docs/paid/sandbox_money_flows.py`. It approves as the buyer in headless Chromium (forcing English with
   `locale.x=en_US`, since PayPal localises by IP) and checks capture, an idempotent re-capture, a refund,
   authorize → void and authorize → capture → refund. It prints statuses only.

## Hosting checklist (Render free + Neon + Cloudflare Pages)

- Webhook: `python docs/paid/setup_paypal_webhook.py` registers `https://<backend>/api/paypal/webhook` and writes
  `PAYPAL_WEBHOOK_ID` (and a `CRON_SECRET`) to `.env`. The webhook registered during development was deleted. Edit the
  script's URL for the new deployment.
- Render env: `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_ENV=sandbox`, `PAYPAL_WEBHOOK_ID`, `CRON_SECRET`
  (all removed from the Qloo deployment).
- Settlement: an in-app loop plus a GitHub Actions call to `POST /api/cron/settle` every 6 hours (each request wakes the
  free instance for ~15 minutes, and the account's 750 free hours a month are shared).
- Content-Security-Policy: add the PayPal JS SDK sources; PayPal's guidance
  (https://developer.paypal.com/sdk/js/v5/best-practices) also asks for `'unsafe-inline'` or a nonce, not added yet.
- The Neon database of the Qloo deployment has no payment tables; give this one its own project or run migration 0003.

## Remaining work

1. The US sandbox accounts and app (above), then the real sandbox run.
2. Run buy → kit → campaign → pledge → close end to end in a browser against the sandbox; write the print styles.
3. Merge later improvements from the main repository.
4. README, the video and the submission texts for the PayPal hackathon.
