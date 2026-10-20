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
4. **Designs the concept.** An agent inspects the strongest gaps with tools and proposes three concepts. Every claim is checked against the evidence: invented places and genres are dropped. Each concept opens into a design sheet: interior mood, materials, offer, a soundtrack from artists that over-index locally, partners, launch, and an interior image.
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
| What does the place look and feel like? | place tags (decor, ambience, setting, menu highlights, offerings) and review keywords of the locals' favorites |

Without Qloo there is no block, no demand, no pull and no design DNA: the product cannot exist.

## What we measured, and changed because of it

We evaluated the pipeline on five sites (Upper East Side, Williamsburg, Lower East Side, East Austin, Zamalek). Two findings changed the method:

- **Comparing a neighborhood with the whole city is biased by scale.** At walk scale "New American" ranks #2 in both the Upper East Side and Williamsburg, but #17 across New York, which looked like a strong local preference. Against same-size areas around each site it ranks #3–#4: no real lift. Blank Space now compares against six same-size areas. Real lifts survive (Upper East Side fine dining #7 here vs #15.5 around; East Austin breweries #2 vs #5.5).
- **Locals' favorite places are mostly the city's famous places.** For the same category, the top-10 favorites of a neighborhood overlap the city's top-10 by 6–10 of 10, so "most favorites are outside the walk" was true everywhere and meant nothing. The places locals love *more than the city does* are informative, and most of them are within a kilometre of the site. Travel ("pull") is now measured on those, and only claimed with at least four of them.

Other safeguards: categories Qloo barely knows locally are flagged as thin data and ranked last; categories whose local favorites are mostly hotels or malls (hotel spas in Cairo, for example) are flagged as atypical; partners are limited to makers, shops and designers (plus teams for sports concepts), never nonprofits, media groups or corporations; negated review keywords ("not crowded") are not counted as complaints.

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
| `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` | no | Any OpenAI-compatible endpoint. Recommended free option: Gemini (`gemini-3.8-flash` via `https://generativelanguage.googleapis.com/v1beta/openai/`). Without it, concepts and design sheets come from deterministic evidence rules |
| `LLM_REASONING_EFFORT`, `LLM_TEMPERATURE` | no | Passed through when set |
| `IMAGE_PROVIDER` | no | `cloudflare` (Workers AI FLUX.1 schnell, free daily allowance) with `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN`, or `openai` with `IMAGE_API_KEY`, `IMAGE_BASE_URL`, `IMAGE_MODEL` |

## Deploy

The repository includes a `Dockerfile` and a `render.yaml` blueprint for Render's free web service. Create a Blueprint from the repository and fill in the secret variables in the dashboard. Any Docker host works the same way: `docker build -t blank-space . && docker run -p 8000:8000 --env-file .env blank-space`.

## Data and privacy

- Qloo responses are cached on the server only (`.cache/`, ignored by git); no Qloo data is stored in this repository.
- Taste data is aggregated and anonymized; Blank Space never asks for personal data.
- Walking catchments come from the public [Valhalla](https://valhalla.github.io/valhalla/) instance run by FOSSGIS on OpenStreetMap data; addresses are geocoded with [Nominatim](https://nominatim.org/). Map tiles © Esri, © OpenStreetMap contributors.

## License

[MIT](LICENSE)
