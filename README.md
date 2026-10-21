# Blank Space

**Drop a pin on an empty storefront. Blank Space reads what the people within a ten-minute walk love, finds what the block is missing, and designs the business that fits.**

Built for the [Qloo Agentic Hackathon](https://qloo.devpost.com/). Taste data by [Qloo](https://www.qloo.com).

Landlords, brokers and founders decide what goes into a vacant unit by gut feel or by expensive foot-traffic reports. A plain language model answers "what should open here?" with the same café-or-wine-bar list for almost any address. Blank Space answers it from evidence: who lives within walking distance, what they engage with more than the neighborhoods around them, how much of it the block already has, and which places they love that are not on the block.

## What it does

1. **Traces the walk.** A real 5, 10 or 15-minute walking catchment over the street network (rivers, parks and highways cut it), not a circle. On Zamalek, Cairo's Nile island, the 10-minute walk is 0.93 km², less than half of an 800 m circle.
2. **Reads the block.** Every place Qloo knows inside the walk: categories, ratings, price levels, what reviews praise and complain about, and which places are rising or fading.
3. **Ranks what is missing.** For each place type locals engage with, it compares:
   - **demand**: the local rank against six same-size areas a few kilometres away;
   - **supply**: places inside the walk against what a block this dense typically holds;
   - **pull**: places locals love *more than the city does*, and whether they sit inside or outside the walk.
4. **Designs the concept.** An agent works like an analyst. It forms hunches the gap table does not cover (sports teams among the area's favorite brands suggest a sports bar) and tests them live against Qloo, scored on the same scale as the table. It asks Qloo what local fans of a category also love: in Fort Greene, sports-bar fans share Bleacher Report, the Giants, 50 Cent and Fabolous with the area's own signature taste. Then it proposes three concepts. Every claim is checked against the evidence: invented places, genres, artists and partners are dropped. Each concept opens into a design sheet: interior mood, materials, offer, a soundtrack from what local fans of the category listen to, partners, launch, and two AI renders: the full interior, and the shopfront from the street with the concept's name on the sign.
5. **Shows the work.** A live survey log, a map with the walk, every place, competitors, arcs to the places locals travel to, and Qloo's taste heatmap for the selected category.

## Why it needs Qloo

| Question | Qloo call |
|---|---|
| What is inside the walk? | `/v2/insights` `filter.type=urn:entity:place`, `filter.location=<walk polygon>`, `filter.location.radius=0` |
| What do locals engage with? | `filter.type=urn:tag`, `filter.tag.types=urn:tag:genre:place`, `signal.location=<walk polygon>` |
| ...compared with similar areas around | the same, with `signal.location=<point>` and `signal.location.radius=<walk radius>` at six reference points |
| How many of each type exist nearby? | `urn:entity:place` with `filter.tags=<genre>` inside the walk and in a wider circle |
| Which places do locals love more than the city does? | `urn:entity:place` ranked by `signal.location=<walk>` versus `signal.location=<20 km>` |
| Who is the crowd? | `filter.type=urn:demographics` over the area's most popular places |
| Which brands and artists over-index here? | `urn:entity:brand` and `urn:entity:artist` with `signal.location`, against three same-size reference areas |
| Where is the taste strongest? | `filter.type=urn:heatmap` with `signal.interests.tags=<genre>` |
| Does the agent's hunch hold up? | `/v2/tags` resolves free text to a place genre, then the supply and favorites calls above, scored on the table's scale |
| What else do local fans of a category love? | `urn:entity:brand` and `urn:entity:artist` with `signal.interests.tags=<genre>` and `signal.location=<site>` |
| What does the place look and feel like? | place tags (decor, ambience, setting, menu highlights, offerings) and review keywords of the locals' favorites |

Without Qloo there is no block, no demand, no pull and no design DNA: the product cannot exist.

## What we measured, and changed because of it

We evaluated the pipeline on five sites (Upper East Side, Williamsburg, Lower East Side, East Austin, Zamalek). Three findings changed the method:

- **Comparing a neighborhood with the whole city is biased by scale.** At walk scale "New American" ranks #2 in both the Upper East Side and Williamsburg, but #17 across New York, which looked like a strong local preference. Against same-size areas around each site it ranks #3–#4: no real lift. Blank Space now compares against six same-size areas. Real lifts survive (Upper East Side fine dining #7 here vs #15.5 around; East Austin breweries #2 vs #5.5).
- **Locals' favorite places are mostly the city's famous places.** For the same category, the top-10 favorites of a neighborhood overlap the city's top-10 by 6–10 of 10, so "most favorites are outside the walk" was true everywhere and meant nothing. The places locals love *more than the city does* are informative, and most of them are within a kilometre of the site. Travel ("pull") is now measured on those, and only claimed with at least four of them.
- **Demographics per category do not separate categories; cross-domain taste does.** Qloo's age and gender skew for sports bars, brunch, seafood, bakeries and toy stores all came back as "45+, leaning female", and several categories returned none, so we dropped an audience-fit tool built on them. What local fans of a category also love is sharply different: sports-bar fans near Fort Greene love the Giants, UFC and DJ Premier; near East Austin, the Cowboys, the Texans and Parker McCollum. The agent and the design sheets use that instead.

Other safeguards: categories Qloo barely knows locally are flagged as thin data and ranked last; categories whose local favorites are mostly hotels or malls (hotel spas in Cairo, for example) are flagged as atypical; partners are limited to makers, shops and designers (plus teams for sports concepts), never nonprofits, media groups or corporations; negated review keywords ("not crowded") are not counted as complaints.

## Running on free AI tiers

Free Gemini keys allow about five requests a minute and a few dozen a day per model, and popular models are often overloaded. While we tested, `gemini-3.8-flash` and `gemini-3.7-flash` timed out on every call for hours and `gemini-3.6-flash` returned "high demand" errors on and off. Blank Space is built for that:

- **A chain of models.** Every call walks `LLM_FALLBACK_MODELS`. A rate-limited model rests for Google's retry delay, one out of daily quota for an hour, an overloaded one for two minutes, a hanging one for five; the next model answers meanwhile.
- **Conversations survive a model change.** If the model running the agent fails between tool turns, the next model continues the same conversation: the old model's thought signatures are replaced with Google's documented `skip_thought_signature_validator` value.
- **Fewer calls.** The agent batches its tool calls, which run in parallel, so a survey takes two or three model turns.
- **No repeated spending.** When a site's Qloo evidence and the prompts are unchanged, the agent's earlier investigation, the design sheets and the no-data baseline are replayed, and the survey log says so.
- **Never a dead end.** When every model is resting, concepts and design sheets come from the evidence rules, and the page says why.

The agent's numbers are grounded: at Williamsburg, Fort Greene, East Austin and Zamalek, every rank, gap score, count, supply ratio and distance it cited matched the evidence. Its wording slipped twice: it called medians averages, and it described the city's famous places as places locals travel to. The evidence it receives now states travel in words, and says plainly when there is no travel signal. Its concept names are checked against nearby places ("Otis & Main" reused the name of Otis, a real restaurant, and was renamed).

## Limitations

- Qloo measures taste and affinity, not foot traffic, rents or sales. A gap is evidence for a decision, not a forecast.
- Coverage is thinner in less digitally active areas, and some categories are tagged broadly (Qloo's "Seafood" includes sushi and poke).
- The gap score is a ranking index within one site, not a probability. Close scores mean close calls.

## Run it locally

Requires Python 3.12 and a Qloo hackathon key.

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
copy .env.example .env            # macOS/Linux: cp .env.example .env, then add your keys
uvicorn app.main:app --port 8765
```

Open http://127.0.0.1:8765. Tests: `pytest` (unit tests for the scoring, plus end-to-end tests that drive the real HTTP app and pipeline against a synthetic Qloo world and a mocked LLM, so they run offline). Full evaluation over the preset sites with live Qloo data: `python scripts/evaluate_sites.py`.

## Configuration

| Variable | Needed | Notes |
|---|---|---|
| `QLOO_API_KEY` | yes | Hackathon key; works only with `QLOO_BASE_URL=https://hackathon.api.qloo.com` |
| `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` | no | Any OpenAI-compatible endpoint. Recommended free option: Gemini (`gemini-3.6-flash` via `https://generativelanguage.googleapis.com/v1beta/openai/`). Without it, concepts and design sheets come from deterministic evidence rules |
| `LLM_FALLBACK_MODELS` | no | Comma-separated models tried in order when the main one is rate limited, out of daily quota, overloaded or hanging. Free tiers are per model, so a chain multiplies capacity. A tool conversation that changes model mid-way continues with Google's documented signature sentinel |
| `LLM_REASONING_EFFORT`, `LLM_TEMPERATURE`, `LLM_TIMEOUT` | no | Passed through when set; the timeout (default 45 s, 25 s for the agent's first turn) marks a model as hanging |
| `AGENT_CACHE` | no | `1` (default) reuses the agent's answers, design sheets and images while a site's Qloo evidence and the prompts are unchanged; the UI says when a run is replayed. `0` always asks the model |
| `IMAGE_PROVIDER` | no | Renders of every concept (the full interior, and the shopfront with its sign), from the first provider in this comma-separated list that answers. Zero-cost setup: `cloudflare,horde`. `cloudflare` is Workers AI's free daily allowance (10,000 neurons, no card): FLUX.1 schnell by default (square, ~130 a day), or `CLOUDFLARE_IMAGE_MODEL=@cf/black-forest-labs/flux-2-klein-4b` (16:9, ~100 a day); needs `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN`. `horde` is [AI Horde](https://github.com/Haidra-Org/AI-Horde), free volunteer GPUs with no key (FLUX.1 schnell; renders queue for one to ten minutes, and a render that is still queued keeps its place when the page asks again). `gemini` uses Google's image models with the agent's key (`IMAGE_MODEL` defaults to `gemini-3.1-flash-image`) and needs billing. `openai` takes `IMAGE_API_KEY`, `IMAGE_BASE_URL`, `IMAGE_MODEL` (e.g. `gpt-image-1`) |
| `IMAGE_DAILY_LIMIT` | no | Most new renders per day (default 60). Renders are cached, each shot is rendered once per prompt, and visitors are rate limited, so a public demo cannot run up the bill |

## Deploy

The repository includes a `Dockerfile` and a `render.yaml` blueprint for Render's free web service. Create a Blueprint from the repository and fill in the secret variables in the dashboard. Any Docker host works the same way: `docker build -t blank-space . && docker run -p 8000:8000 --env-file .env blank-space`.

## Data and privacy

- Qloo responses are cached on the server only (`.cache/`, ignored by git); no Qloo data is stored in this repository.
- Taste data is aggregated and anonymized; Blank Space never asks for personal data.
- Walking catchments come from the public [Valhalla](https://valhalla.github.io/valhalla/) instance run by FOSSGIS on OpenStreetMap data; addresses are geocoded with [Nominatim](https://nominatim.org/). Map tiles © Esri, © OpenStreetMap contributors.

## License

[MIT](LICENSE)
