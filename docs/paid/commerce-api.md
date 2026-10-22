# Walk-in: accounts, launch kit and pledges — the API contract

Both the backend and the frontend build to this. If something here cannot work, stop and tell the lead rather than
inventing a different shape. All JSON. Errors are FastAPI's `{"detail": "plain-language message"}` unless stated.
Amounts are strings with two decimals (`"19.00"`), never floats. Times are ISO 8601 UTC strings.

## Product rules (decided by the owner)

- Anyone can run a survey without an account (judges must be able to try it instantly).
- Signing in (Google) saves surveys, kits and campaigns to "My places" on any device. Surveys run earlier in the same
  browser are attached to the account at sign-in.
- Buying the $19 launch kit and starting a pledge campaign require sign-in.
- Supporters pledge with PayPal only, no account.
- A campaign starts from a kit the owner bought (the kit's survey and concept).
- PayPal is in sandbox: the UI must say "Test mode: PayPal sandbox, no real money" wherever money appears.

## Cookies and security

- `walkin_session`: random 32-byte token (base64url). The database stores only its SHA-256. HttpOnly, SameSite=Lax,
  Path=/, Secure when the site is served over https (PUBLIC_URL https or X-Forwarded-Proto https). 30 days, extended
  on use at most once a day. Sign-out deletes the row and clears the cookie.
- `walkin_device`: random 128-bit id, HttpOnly, SameSite=Lax, 400 days. Set on the first `/api/run` if missing. Each
  survey stores it (`surveys.device_id`), and signed-in runs also store `surveys.user_id`. At sign-in, surveys with this
  device id and no user are attached to the user.
- Unsafe methods (POST, PUT, PATCH, DELETE) under `/api/` must come from an allowed origin when an `Origin` header is
  present: PUBLIC_URL's origin, the request's own origin, and `ALLOWED_ORIGINS` (comma-separated; in development
  `http://localhost:5173` and `http://127.0.0.1:5173`). Otherwise 403. The PayPal webhook and cron endpoints are exempt
  (they authenticate otherwise).
- Development sign-in (`POST /api/auth/dev`) exists only when `AUTH_DEV_LOGIN=true` AND PUBLIC_URL is not https. It is
  never available on the hosted site.

## Endpoints

### Config and session

`GET /api/config` → public settings for the web app
```json
{
  "google_client_id": "123.apps.googleusercontent.com" | null,
  "dev_login": false,
  "paypal": { "enabled": true, "client_id": "A...", "environment": "sandbox", "currency": "USD", "kit_price": "19.00" }
}
```
`paypal.client_id` is the public REST client id (the JS SDK needs it). `enabled` is false when PayPal is not configured;
the UI then hides buying and pledging and says why.

`POST /api/auth/google` body `{ "credential": "<Google ID token from Google Identity Services>" }` → `200 Me` and sets
`walkin_session`. The server verifies the token's signature against Google's JWKS
(`https://www.googleapis.com/oauth2/v3/certs`, cached per Cache-Control), `iss` (`accounts.google.com` or
`https://accounts.google.com`), `aud` == GOOGLE_CLIENT_ID, `exp`, and `email_verified`. 400 for a bad token, 503 when
GOOGLE_CLIENT_ID is not set.

`POST /api/auth/dev` body `{ "email": "tester@example.com", "name": "Tester" }` → `200 Me` (development only, see above;
404 otherwise).

`POST /api/auth/logout` → `204`, clears the cookie.

`GET /api/me` → `200 { "user": User | null }` (never 401, so the app can call it on every load).
```ts
type User = { id: string; email: string; name: string; picture: string | null };
type Me = { user: User };
```

`GET /api/me/places` (signed in, else 401) →
```ts
{
  surveys: { id: string; label: string; intent: "explore" | "open" | "improve"; status: "running" | "complete" | "failed";
             created_at: string; headline: string | null /* the top concept's name, or the top gap */; url: string /* /s/{id} */ }[];
  kits: { token: string; survey_id: string; index: number; name: string /* business name */; status: KitStatus;
          created_at: string; url: string /* /k/{token} */ }[];
  campaigns: { id: string; title: string; status: CampaignStatus; supporters: number; goal: number;
               deadline: string; url: string /* /p/{id} */ }[];
}
```
Newest first, at most 100 of each.

### The launch kit ($19, PayPal CAPTURE)

`GET /api/kits/mine?run_id=...&index=N` (signed in) → `{ "kit_url": "/k/{token}" | null }`: whether the user already
owns the kit for this concept, so the UI shows "Open your kit" instead of the PayPal buttons.

`POST /api/checkout` (signed in) body `{ "run_id": "...", "index": N }` → `{ "order_id": "<PayPal order id>" }`.
Creates a PayPal order (intent CAPTURE, the kit price, `custom_id` identifying our order, description
"Walk-in launch kit: {business name}") and stores it with status `created` and the user. 404 when the survey or concept
does not exist; 409 `{"detail": "...", "kit_url": "/k/..."}` when the user already owns this kit.

`POST /api/checkout/{order_id}/capture` (signed in, the order's user) → `{ "token": "...", "kit_url": "/k/{token}" }`.
Captures the order and checks it with `paypal.paid_in_full` (amount, currency, custom_id). On success: order
`completed`, a kit row (`building`) with a random 32-byte token, and the kit is built in the background (design the
concept first if it has no design sheet, then `kit.build_kit`; the payload includes the dossier), ending `ready` or
`failed`. Idempotent: capturing again returns the same kit. When PayPal declines the instrument
(`INSTRUMENT_DECLINED`), answer `402 {"detail": "...", "retry": true}` so the PayPal buttons can restart.

`GET /api/kits/{token}` (anyone with the link) →
```ts
type KitStatus = "building" | "ready" | "failed" | "refunded";
{
  token: string; status: KitStatus; survey_id: string; index: number; name: string; created_at: string;
  survey_url: string;      // /s/{survey_id}?sheet={index}
  is_owner: boolean;       // the signed-in user bought it
  kit: object | null;      // build_kit's payload when ready (concept, claims, copy, poster, links, dossier, rejected, notes, mode, model, built_at)
  error: string | null;    // why it failed, in plain words
  campaign_url: string | null;  // its pledge campaign, when one exists
  refundable_until: string | null;  // owner only: refunds are self-service for 14 days
}
```
The page polls every 2 s while `building`.

`POST /api/kits/{token}/retry` (owner, status `failed`) → `202` and rebuilds.

`POST /api/kits/{token}/refund` (owner, within 14 days of purchase) → `{ "status": "refunded" }`: refunds the capture
through PayPal and revokes the kit.

### Pledge campaigns (PayPal AUTHORIZE, then capture or void)

`POST /api/campaigns/draft` (signed in, kit owner) body
`{ "kit_token": "...", "amount": "25.00", "goal": 25, "deadline": "<ISO>", "discount": "10% off every visit in the first year" | null }`
→ `{ "title": "...", "pitch": "...", "perks": ["..."], "how_it_works": "..." , "problems": [] }`, from
`pledges.draft_offer` (the owner's terms go in unchanged). `problems` lists why the terms are not allowed
(`pledges.validate_campaign`); then no draft is written.

`POST /api/campaigns` (signed in, kit owner) body
`{ "kit_token": "...", "amount": "25.00", "goal": 25, "deadline": "<ISO>", "discount": "..." | null, "title": "...", "pitch": "...", "perks": ["..."] }`
→ `{ "id": "...", "url": "/p/{id}" }`. Validates the terms (deadline at most 27 days away), re-checks the edited text
with the same rules as the draft (422 with the problems when it breaks one), stores the campaign `open`. One open
campaign per kit (409 with its url otherwise).

`GET /api/campaigns/{id}` (anyone) →
```ts
type CampaignStatus = "open" | "collected" | "partial" | "expired" | "cancelled";
{
  id: string; status: CampaignStatus; accepting: boolean /* still takes pledges */;
  name: string; neighborhood: string | null; concept: { genre: string; summary: string } ;
  title: string; pitch: string; perks: string[]; how_it_works: string;
  amount: string; currency: string; goal: number; deadline: string; closed_at: string | null;
  progress: { supporters: number; goal: number; remaining: number; percent: number; total: string; funded: boolean };
  is_owner: boolean;
  owner?: {   // only for the owner
    counts: Record<string, number>;   // pledges by status
    report: string[] | null;          // the settlement report in plain words, once settled
  };
  survey_url: string;
}
```

`POST /api/campaigns/{id}/pledges` (anyone; rate-limited) → `{ "order_id": "..." }`: a PayPal order with intent
AUTHORIZE for the campaign's amount, `custom_id` identifying the pledge, stored as pledge `created`. 409 when the
campaign no longer accepts pledges.

`POST /api/campaigns/{id}/pledges/{order_id}/authorize` (anyone) →
`{ "status": "authorized", "supporter_number": 8, "withdraw_url": "/p/{id}?withdraw={token}", "progress": {...} }`.
Authorizes the order, checks it with `paypal.authorized_in_full`, stores the hold (authorization id, payer id,
authorized_at, expires_at) and a withdraw token (stored hashed). 402 `{"detail": "...", "retry": true}` on
`INSTRUMENT_DECLINED`.

`POST /api/campaigns/{id}/withdraw` body `{ "token": "..." }` → `{ "status": "voided", "progress": {...} }`: voids the
supporter's hold while the campaign still accepts pledges.

`POST /api/campaigns/{id}/close` (owner) → the campaign view: closes it now and settles at once (funded: capture every
hold; short: void them all).

`POST /api/campaigns/{id}/cancel` (owner) → the campaign view: voids every hold, status `cancelled`.

### Settlement, webhook, cron

- A background loop (every 60 s, and at startup) settles campaigns that are past their closing time and not final, and
  keeps collecting `partial` ones, through `pledges.decide` / `pledges.settle`. The "funded" decision is saved before
  the first capture. One campaign at a time.
- `POST /api/cron/settle` with header `X-Cron-Secret: <CRON_SECRET>` → runs the same settlement once (a scheduled
  GitHub Action calls it hourly, so a sleeping free instance still settles on time). 404 when CRON_SECRET is unset.
- `POST /api/paypal/webhook` → verifies the event with PayPal (`PAYPAL_WEBHOOK_ID`; unverified events are rejected
  with 400), stores it once by event id, and updates orders, kits (refunds) and pledges (captures, voids, denials).

## Web app routes

- `/` the brief, `/s/{id}` a survey (exist).
- `/me` My places (signed in; otherwise a sign-in prompt).
- `/k/{token}` the kit: concept, ad copy per channel with copy buttons, the poster (SVG with a QR code of its tracked
  link), tracked links, the dossier's sections, "Start a founding-supporter campaign", and refund (owner).
- `/k/{token}/dossier` the dossier as a print page ("Save as PDF" calls `window.print()`).
- `/p/{id}` the pledge page (public), with the owner's controls when `is_owner`.
- The server already serves `/s/*`, `/k/*` and `/p/*` as the web app; `/me` must be added.

## New settings (environment)

`GOOGLE_CLIENT_ID`, `SESSION_DAYS` (30), `AUTH_DEV_LOGIN` (false), `ALLOWED_ORIGINS`, `CRON_SECRET`,
`KIT_REFUND_DAYS` (14). Existing: `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_ENV`, `PAYPAL_WEBHOOK_ID`,
`KIT_PRICE`, `KIT_CURRENCY`, `PUBLIC_URL`, `DATABASE_URL`.
