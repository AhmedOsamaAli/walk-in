# Walk-in MCP server

Walk-in as a tool for any AI assistant: Claude Desktop, VS Code Copilot, or any other MCP client. It wires Walk-in, and
the Qloo taste data behind it, into an agent that already exists.

Walk-in surveys an empty storefront:

- it traces the real walk or drive area around it;
- it reads Qloo's taste data for the people in that area;
- it ranks the kinds of places the area is missing;
- it designs concepts checked against that evidence;
- its web page builds design sheets and a free launch kit.

The server is one file, [`walkin_mcp.py`](walkin_mcp.py). It speaks MCP over stdio and calls only Walk-in's public
HTTP API, so it needs no keys.

## Tools

| Tool | What it returns | Cost |
|---|---|---|
| `survey_storefront` | A survey of a site, given as a `place` (address or neighborhood) or `lat`/`lon`. Options: `travel` (`walk`, `drive` or `distance`), `minutes` (5–60) or `km` (1–100), `ages` (`all`, `under_25`, `25_34`, `35_54`, `55_plus`) and an optional `business` to test. Returns the area, the age focus, the top 5 gaps with their reading and evidence, the concepts, the verdict and chain line for a business tested, and the survey link. | Takes 1 to 3 minutes. Spends Qloo and AI quota. Walk-in allows a few surveys per hour from one address. |
| `list_examples` | The finished example surveys anyone can open: site, area, what is most missing, concepts, and links to the survey, its launch kit and its printable report. | Free |
| `get_survey` | A survey read again by its run id or its `/s/` link, summarized like `survey_storefront`. It also gives the rest of a survey that was still running. | Free |

How the calls map to the API:

- `survey_storefront` geocodes a `place` with `GET /api/geocode` and takes the first match.
- It then streams `GET /api/run` as server-sent events, until `done` or `error`.
- With a `business`, the survey runs with intent `open` (the web app's "Test my idea"); without one, it runs `explore`.
- `list_examples` calls `GET /api/examples`.
- `get_survey` calls `GET /api/runs/{run_id}`.

The summaries only repeat what Walk-in's events say, in Walk-in's words. Each one ends with the survey link (design
sheets and the free launch kit are there) and the data credit: Qloo taste data, OpenStreetMap, Valhalla routing.

Each survey step is sent as an MCP progress notification ("Tracing a 10-minute walk over the street network"). The
note sent when the survey starts carries its link.

## Setup

Python 3.10 or newer:

```powershell
pip install -r mcp_server/requirements.txt
```

To check it starts: `python mcp_server/walkin_mcp.py` waits silently for a client on stdin (Ctrl+C stops it). To try
the tools by hand, use the MCP Inspector: `npx @modelcontextprotocol/inspector python mcp_server/walkin_mcp.py`.

Settings, from the environment:

| Variable | Default | What it sets |
|---|---|---|
| `WALKIN_URL` | `https://walkin-app.pages.dev` | The Walk-in site. Its front door forwards `/api` to the survey engine. A local server works too: `http://127.0.0.1:8770` under uvicorn, `http://127.0.0.1:8000` in Docker. |
| `WALKIN_WAIT_SECONDS` | `240` | How long `survey_storefront` waits for a survey, 10 to 600. See [Limits](#limits). |

## Client config

Use the absolute path to `walkin_mcp.py`. `python` must be the interpreter you installed the requirements into; give
its full path if another one comes first on `PATH`.

### Claude Desktop

Edit `claude_desktop_config.json`:

- on Windows, `%APPDATA%\Claude\claude_desktop_config.json`;
- on macOS, `~/Library/Application Support/Claude/claude_desktop_config.json`.

Then restart Claude Desktop.

```json
{
  "mcpServers": {
    "walkin": {
      "command": "python",
      "args": ["C:\\path\\to\\walk-in\\mcp_server\\walkin_mcp.py"],
      "env": {
        "WALKIN_URL": "https://walkin-app.pages.dev",
        "WALKIN_WAIT_SECONDS": "50"
      }
    }
  }
}
```

### VS Code (Copilot agent mode)

Add `.vscode/mcp.json` to the workspace, or run **MCP: Open User Configuration** to add it for every workspace:

```json
{
  "servers": {
    "walkin": {
      "type": "stdio",
      "command": "python",
      "args": ["${workspaceFolder}/mcp_server/walkin_mcp.py"],
      "env": { "WALKIN_URL": "https://walkin-app.pages.dev" }
    }
  }
}
```

### Other MCP clients

Any client that launches a stdio server works: command `python`, with the path to `walkin_mcp.py` as its argument.

## Example prompts

- "Show me Walk-in's finished examples." (`list_examples`)
- "What's missing within a 10-minute walk of 120 Bedford Ave, Brooklyn?" (`survey_storefront`)
- "I want to open a bakery in Zamalek, Cairo, for people aged 25 to 34. Is it a good idea?" (`business` and `ages`)
- "Would a Starbucks work on the Upper East Side?" (a verdict, plus how many Starbucks stores are already nearby)
- "Survey a 15 km drive around 30.2622, -97.7247 for people 55 and over." (`lat`/`lon`, `travel: distance`, `km`)
- "Read survey 76cc5edebd18 again." or "What did that survey find in the end?" (`get_survey`)

## Example output

`get_survey("76cc5edebd18")`, read from the live site (trimmed):

```text
## Walk-in survey: Williamsburg, Brooklyn
- Area: 10-minute walk (1.64 km², traced over the street network)
- Age focus: everyone

**Top gaps** (5 of 8 categories ranked, most missing first)
1. **Seafood**: People here travel for it
   - People here rank seafood #7 among the place types they engage with, about as high as the areas around (#7).
   - 6 seafood places inside the 10-minute walk (5 on Qloo, 1 more on OpenStreetMap), about what a block this dense holds (about 7.4).
   - OpenStreetMap shows 1 more seafood place inside the walk that Qloo doesn't list: Rosarito Fish Shack.
   - All 7 seafood places people here love more than the rest of the city does are outside the walk, a median 3.4 km away: Cervo's, Astoria Seafood and The Mermaid Inn.
2. **New American**: Top demand
   ...

**Concepts**
1. **The Anchor & Fin**: A seafood bar specializing in fresh catches and small plates, offering a destination for the flavors people here travel for.
2. **The Morning Glory**: Brunch for the neighborhood's #1 interest, better than the 27 already inside the walk.
3. **Meadow Kitchen**: New American for the neighborhood's #2 interest, better than the 9 already inside the walk.
4. **Reef & Roast** (wildcard: two loves combined, untested): A seafood place and a coffee shop in one: two things people here love, and nothing inside the 10-minute walk is both.

Survey, design sheets and the free launch kit: https://walkin-app.pages.dev/s/76cc5edebd18
Data: Qloo taste data · OpenStreetMap (© OpenStreetMap contributors) · Valhalla routing.
```

With a `business`, the verdict and the chain line come first. This one is from a saved Upper East Side survey that
tested Starbucks:

```text
- Testing: Starbucks

**Verdict:** Coffee Shop is a weak gap here (#9 of 9): demand and supply here are close to what the areas around show.
**Chain:** 6 Starbucks locations are already inside the 10-minute walk, and 14 within a 20-minute walk.
```

A themed wild card is listed with its theme and what happens there, each line naming titles people here over-index on.
This one is from an East Austin survey (a 15-minute drive) run on the evidence rules:

```text
4. **Cliffhanger Bar** (themed wild card: reality TV, untested): A cocktail bar with reality-TV watch parties: people here over-index on reality TV, and nothing inside the 15-minute drive is known for it.
   - Watch parties for Jersey Shore: Family Vacation and Property Brothers
   - Recap nights on Scrubbing In with Becca Tilley & Tanya Rad and Off The Vine with Kaitlyn Bristowe
```

## Limits

- **Rate and cost.** Walk-in allows a few surveys per hour from one address; past that, the tool says so in a plain
  sentence. Each survey spends Qloo and AI quota. `list_examples` and `get_survey` are free: they read what was saved.
- **Time.** A survey takes 1 to 3 minutes. After 15 quiet minutes the free server sleeps, and it takes up to a minute
  to wake; the tool waits through that. It waits up to `WALKIN_WAIT_SECONDS` (4 minutes by default). After that, it
  returns what the survey had found so far, with its run id. The survey keeps running at Walk-in, and `get_survey`
  reads the rest.
- **Client timeouts.** Clients differ in how long they wait for a tool. Claude Desktop stops after about a minute, so
  the config above sets `WALKIN_WAIT_SECONDS` to 50: the gaps usually arrive in time, and the assistant can call
  `get_survey` for the concepts. Clients that restart their timeout on progress keep waiting: the server sends a
  progress notification for every step, and at least every 15 seconds.
- **Scope.**
  - `survey_storefront` covers "what is missing here" and "test my idea". "Improve my place" is not offered, nor are
    the web brief's unit details (size, kitchen, outdoor space), notes and focus.
  - Design sheets, launch kits and reports are made on the survey's page, not by the tools.
  - The summary shows the top 5 gaps; the survey page has the whole table, the maps and the places behind the
    evidence.
- **Places.** Walk-in's address search (OpenStreetMap's Nominatim) takes its first match, and the summary names the
  site it found. Give `lat` and `lon` when a name is ambiguous, or when the search is slow or down: the tool says so.
- **Not in My places.** Surveys made through the tools belong to no Walk-in account, so they don't show in My places.
  Keep the link.
- **Privacy.** The tools send the place, coordinates and brief to `WALKIN_URL` only. Nothing is stored locally.
- **Data.**
  - Qloo taste data.
  - OpenStreetMap: © OpenStreetMap contributors, under the Open Database License. Walk-in uses its streets and places
    to trace areas and cross-check gaps.
  - Valhalla routing, on FOSSGIS's public instance.
  - Nominatim address search.

## Tests

Tests use `httpx.MockTransport` and need no network:

```powershell
python -m pytest -q tests/test_mcp_server.py
python -m ruff check mcp_server tests/test_mcp_server.py
```

They cover:

- server-sent events: keep-alive comments, chunks split mid-line and mid-character, CRLF;
- geocode, then run;
- intent `open`, with its verdict and chain line;
- the 429 and 400 messages, and other failures;
- waiting through a waking server, and a survey still running when the wait ends;
- `list_examples` and `get_survey`;
- all three tools over the MCP protocol, with progress notifications.
