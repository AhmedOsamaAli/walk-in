# Walk-in Founders: the contract

Walk-in finds what an empty storefront's block is missing. **Founders** lets the neighbors back it with PayPal before
the lease is signed: they pledge, PayPal only holds the money, and everyone is charged only if enough people join by
the deadline. If the goal is missed, every hold is released and nobody pays.

This is the PayPal AI Hackathon edition (deadline Nov 12, 2026, noon Pacific; judging Dec 1–15). Every builder codes to
this file. If something here cannot work, stop and tell the lead rather than inventing a different shape. All JSON.
Errors are FastAPI's `{"detail": "plain words"}`. Amounts are strings with two decimals (`"25.00"`), never floats.
Times are ISO 8601 UTC strings.

The Oct 22 snapshot (`git show d056ee6:<path>`) already holds a reviewed PayPal REST client
(`app/payments/paypal.py`), the pledge rules (`app/payments/pledges.py`), settlement, campaign routes, webhooks, a fake
PayPal for tests and a pledge page. It was built around a paid $19 kit. **The kit is free now**: port what still fits,
drop the kit purchase (`app/commerce.py`, `app/sales.py`, the paid `routes/kits.py`, `KitOffer`, checkout endpoints).

## Product rules

1. **Supporters** pledge with PayPal only, without an account.
2. **Owners** sign in with Google to start a campaign. Any ready launch kit can be its basis, the finished examples
   included (in December no new survey can run: Qloo's hackathon key is switched off after its hackathon closes). The
   campaign belongs to the signed-in user who starts it. One open campaign per user per kit.
3. **The owner chooses the money terms**: one pledge amount ($5.00–$200.00), the goal in supporters (3–500), the
   deadline (1–27 days away: PayPal holds an authorization for 29 days and settlement keeps 2 of them), an optional
   perk line ("10% off every visit in the first year") and the PayPal email that receives the money.
4. **The AI writes the words**: `draft_offer` drafts the title, pitch, perks and "how it works" from the kit's concept
   and the survey's evidence. The owner edits them; the server re-checks the edited words with the same rules (no
   amounts or prices but the owner's, no counts the evidence does not give, no invented names, no "only"/"first" claims
   the evidence does not support). The AI never sets a number.
5. **A pledge is a PayPal order with intent AUTHORIZE.** On the web the supporter approves in the PayPal buttons (JS SDK
   v6). For an AI assistant (MCP) the server creates the order with return and cancel URLs and hands back PayPal's
   approval link; the supporter approves in PayPal, PayPal sends them to `/p/{id}?pledge={orderId}`, and that page
   authorizes it. A held pledge counts toward the goal; a declined one never does. A supporter may withdraw a pledge
   while the campaign is open (the hold is voided).
6. **Closing.** At the deadline, or early by the owner once the goal is met. Funded: capture every valid hold
   (reauthorize first when past PayPal's 3-day honor period). Not funded, or cancelled by the owner: void every hold.
   Settlement is idempotent and resumable: the funded decision is stored before the first capture.
7. **Payout.** Once collected, PayPal Payouts sends the net collected total (after PayPal's fees, from the captures'
   `seller_receivable_breakdown`) to the owner's PayPal email, idempotent per campaign (`sender_batch_id`). The owner
   sees its status. In production this would be PayPal's marketplace onboarding, money straight to the owner; the
   README says so.
8. **Test mode**, wherever money appears: "Test mode: PayPal sandbox, no real money."
9. **Webhooks**, verified with PayPal's verify-webhook-signature API on the raw body, keep pledges and the payout in
   sync. Unknown or replayed events are acknowledged and ignored.
10. **Agents never touch payment credentials.** They find campaigns and prepare a pledge; a person approves every
    pledge in PayPal.
11. **Surveys can be paused** (`SURVEYS_PAUSED=true`, for the judging weeks after Qloo's key is gone): `/api/run`
    answers 503 "New surveys are paused; open one of the surveyed storefronts", and the web app shows the surveyed
    storefronts instead of the brief's survey button.

## Endpoints

`GET /api/config` (exists; extend it) adds:
```ts
paypal: { enabled: boolean; client_id: string | null; environment: "sandbox" | "live"; currency: "USD" };
surveys_paused: boolean;
```
`enabled` is false when PayPal is not configured; the web app then hides pledging and says why.

`POST /api/campaigns/draft` (signed in) body
`{ kit_token, amount: "25.00", goal: 40, deadline: "<ISO>", perk: string | null }`
→ `{ title, pitch, perks: string[], how_it_works, problems: string[] }`. `problems` lists why the terms are not allowed;
then no draft is written (and no model is called).

`POST /api/campaigns` (signed in) body
`{ kit_token, amount, goal, deadline, perk, payout_email, title, pitch, perks: string[] }` → `{ id, url: "/p/{id}" }`.
422 with `problems` when a term or an edited line breaks a rule; 409 `{detail, url}` when this user already has an open
campaign for this kit.

`GET /api/campaigns/{id}` (anyone) →
```ts
type CampaignStatus = "open" | "funded" | "collected" | "partial" | "expired" | "cancelled";
type Campaign = {
  id: string; status: CampaignStatus; accepting: boolean;   // still takes pledges
  kit_token: string; kit_url: string; survey_url: string;
  name: string;                                             // the business, from the kit
  place: { label: string; lat: number; lon: number; area: string };  // "10-minute walk"
  concept: { genre: string; summary: string };
  evidence: string[];                                       // up to 3 lines from the survey: why this, why here
  title: string; pitch: string; perks: string[]; how_it_works: string;
  amount: string; currency: "USD"; goal: number; deadline: string; closed_at: string | null;
  progress: { supporters: number; goal: number; remaining: number; percent: number; total: string; funded: boolean };
  is_owner: boolean;
  owner?: {                                                 // the owner only
    counts: Record<string, number>;                         // pledges by status
    report: string[] | null;                                // the settlement, in plain words, once settled
    payout: { status: "none" | "pending" | "paid" | "failed"; amount: string | null; email: string };  // email masked: "o***@example.com"
  };
};
```

`GET /api/campaigns?lat=&lon=&km=` (anyone; agent-friendly) → open campaigns within `km` (default 25, max 100), nearest
first; without `lat`/`lon`, open campaigns newest first. At most 50:
`{ campaigns: { id, url, title, name, place: {label, lat, lon}, distance_km: number | null, amount, goal, supporters, deadline }[] }`.

`POST /api/campaigns/{id}/pledges` (anyone) body `{ flow: "buttons" | "redirect" }` → `{ order_id, approve_url: string | null }`.
Creates the AUTHORIZE order for the campaign's amount (`custom_id` = our pledge id, description "Founding supporter:
{name}"). `redirect` adds return/cancel URLs (`{PUBLIC_URL}/p/{id}?pledge={orderId}` and `?cancelled=1`) and returns
PayPal's approval link. 409 when the campaign no longer accepts pledges. Rate-limited per address.

`POST /api/campaigns/{id}/pledges/{order_id}/authorize` (anyone) → `{ status: "authorized" | "declined", progress }`.
Idempotent. `402 {detail, retry: true}` when PayPal declines the instrument, so the buttons can restart.

`POST /api/campaigns/{id}/pledges/{order_id}/withdraw` (anyone holding the order id, while open) → `{ status: "withdrawn", progress }`.

`POST /api/campaigns/{id}/close` (owner) → settles now when funded (or when the deadline has passed) → the campaign.
`POST /api/campaigns/{id}/cancel` (owner, short of the goal) → voids every hold → the campaign.

`POST /api/paypal/webhook` (PayPal; verified) and `POST /api/cron/settle` (header `X-Cron-Secret: CRON_SECRET`) settle
what is due. Both are exempt from the Origin check.

`GET /api/me/places` (exists; extend it) adds `campaigns: { id, title, status, supporters, goal, deadline, url }[]`.

`GET /api/kits/{token}/campaigns` → `{ campaigns: { id, url, is_owner, status, amount, goal, supporters, deadline }[] }`:
the kit's open campaigns, the viewer's own first, then newest first; never cached (no-store). The poster uses the
viewer's own open campaign. They are not part of `GET /api/kits/{token}`: that page is the same for every visitor, so
memory and the front door keep it (app/cache_policy.py), while campaigns change with every pledge and depend on who asks.

## Pages

- `/p/{id}`: the campaign. Supporter view: the business, the place and its area, why this and why here (the evidence),
  the pitch and perks, the progress toward the goal, the deadline, "Pledge $25 with PayPal" (the buttons), and in plain
  words: "PayPal holds $25. You are charged only if 40 neighbors join by Nov 30; otherwise the hold is released."
  After pledging: thanks, the progress, and how to withdraw. Owner view adds the counts, close early (once funded),
  cancel, the settlement report and the payout.
- `/founders`: open campaigns, newest first, and "Start one from a launch kit".
- The launch kit page gets a **Founders** tab: start a campaign (the form, the AI draft, edit, publish), or this user's
  campaign for the kit. Signed out: "Sign in with Google to start one."
- The **window poster**: when the kit has an open campaign, its QR code opens the campaign and the poster says, from
  the campaign's own terms (not from the model): "Back it before it opens: pledge $25, charged only if 40 neighbors
  join by Nov 30."
- My places lists the user's campaigns. The top bar links "Founders".

## Content-Security-Policy additions (the server's in `app/main.py`, `frontend/public/_headers`, `vite.config.ts`)

`script-src` and `connect-src` add `https://www.sandbox.paypal.com https://www.paypal.com`; `frame-src` adds
`https://www.sandbox.paypal.com https://www.paypal.com`; `img-src` already allows `https:`. Change all three together.

## Agents (MCP server, `mcp_server/walkin_mcp.py`)

New tools beside the survey ones: `find_campaigns` (a place or lat/lon, km), `get_campaign` (id or link) and
`back_campaign` (id or link): it prepares a pledge with `flow: "redirect"` and returns the approval link with the terms
in plain words. The person approves in PayPal; the agent never sees a card or an account.

## Who builds what

- **P (payments backend):** `app/payments/**`, `app/settlement.py`, `app/db/campaigns.py`, `app/db/events.py`, the
  campaign, pledge, payout and event tables in `app/db/tables.py` and a new migration, `app/routes/campaigns.py`,
  `app/routes/hooks.py`, `app/config.py`, `app/schemas.py`, the router seam and CSP in `app/main.py`, `/api/config` and
  `/api/me/places` in `app/routes/account.py` and `app/db/accounts.py`, the kit's `campaigns` in `app/routes/kits.py`,
  `SURVEYS_PAUSED`, `.env.example`,
  `render.yaml`, `.github/workflows/settle.yml`, `docs/founders/sandbox_money_flows.py` and
  `docs/founders/setup_paypal_webhook.py`, and their tests.
- **W (web):** `frontend/**`: the pages, the Founders tab, the poster's campaign QR and line, the top bar link, My
  places, the PayPal buttons, the CSP in `_headers` and `vite.config.ts`, the surveyed-storefronts view when surveys are
  paused.
- **A (agents):** `mcp_server/**`, `frontend/public/llms.txt` and `docs/founders/agents.md`.
- **Lead:** this file, the README, deployment, data, the film, the submission.
