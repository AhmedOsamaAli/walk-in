# Walk-in vs a plain chatbot on 15 real storefronts

**Headline.** Across 15 storefronts in 15 cities on 6 continents, a plain chatbot's top pick was a coffee shop, café or bakery at 10 of them, while Walk-in's 15 top picks were 14 different kinds of place; by Qloo's count, though, both sides' picks faced the same median of 8 competitors inside the 10-minute walk.

## What the numbers say

- **(a) Sameness: the clear result.** The chatbot's top pick was a coffee shop, café or bakery at 10 of 15 storefronts, each time as a compound such as 'Specialty Coffee & Artisanal Bakery', and a coffee shop, café or bakery was among its three suggestions at 14. Mapped to Qloo's place genres, its 15 top picks were 8 kinds (Coffee shop ×5, Bakery ×3, Cafe ×2). Walk-in's were 14 kinds (repeated: Pub ×2), with a coffee shop, café or bakery at 1. The two sides never named the same genre; both chose a café concept only in Cairo (Coffee shop vs Cafe). This part uses no Walk-in data.
- **(b) Competition: level.** By Qloo's count both sides' top picks had the same median, 8 competitors inside the walk; the chatbot's had more at 9 sites, Walk-in's at 5, with 1 tie (sign test p = 0.42). OpenStreetMap's medians are 14 and 7.5 (7 sites to 4, p = 0.55), but it is not a fair referee here: a café carries one tag almost everywhere (amenity=cafe), while Walk-in's cuisine-level kinds rest on optional cuisine tags. In Paris, OpenStreetMap shows 114 places tagged as cafés inside the walk and 1 tagged 'brunch', where Qloo lists 19 and 10. The claim that the chatbot picks what the block already has plenty of is not supported by the counts.
- **(c) Relative supply (Walk-in's own measure).** The chatbot's picks sat where the surroundings predict (median 1.00; 4 over-supplied, 3 under-supplied); Walk-in's sat lower (median 0.89; 0 over, 7 under), which is partly what its score is built to find.
- **(d) Local demand.** 6 of the chatbot's 15 top picks were among the 15 place types people around the storefront engage with most, and 5 were outside their top 50. Walk-in's always are: it only considers the top 8. None of the chatbot's 15 picks was both under-supplied and in that top 15; 7 of Walk-in's were.

## Aggregate metrics (top picks)

| Metric | Plain chatbot | Walk-in |
|---|---|---|
| Top picks measured (mapped to a Qloo place genre) | 15 of 15 | 15 of 15 |
| (a) Distinct Qloo genres among the 15 top picks | 8 (Coffee shop ×5, Bakery ×3, Cafe ×2) | 14 |
| (a) Top pick is a coffee shop, café or bakery | 10 of 15 | 1 of 15 |
| (a) Coffee shop, café or bakery among the three suggestions | 14 of 15 | 2 of 15 |
| (b) Median competitors inside the walk, Qloo | 8 | 8 |
| (b) Paired, Qloo: sites where this side's pick has more | 9 | 5 (1 tie; p = 0.42) |
| (b) Median competitors inside the walk, OpenStreetMap (independent; tagging-skewed) | 14 (n=12) | 7.5 (n=12) |
| (b) Paired, OpenStreetMap | 7 | 4 (0 ties; p = 0.55) |
| (c) Over-supplied (relative supply ≥ 1.2) | 27% (4/15) | 0% (0/15) |
| (c) Under-supplied (≤ 0.8) | 20% (3/15) | 47% (7/15) |
| (c) Median relative supply | 1.00 | 0.89 |
| (d) Among people's top 15 place types here | 40% (6/15) | 100% (15/15) (by construction) |
| (d) Median rank people here give the pick | 23 | 4 |
| (c)+(d) Under-supplied and in people's top 15 | 0% (0/15) | 47% (7/15) (its objective) |

Chatbot models that answered: gemini-3.6-flash ×11; after HTTP 503 (overloaded) errors, gemini-3.5-flash ×1, gemini-2.5-flash ×3. Coffee/café/bakery top picks by model: gemini-3.6-flash: 8 of 11; gemini-3.5-flash: 0 of 1; gemini-2.5-flash: 2 of 3. LLM calls used: 17 of 40. Walks: 15 of 15 traced on the street network. OpenStreetMap: overpass.openstreetmap.fr (data as of 2026-08-10): 13 walks; maps.mail.ru (data as of 2026-10-24): 2 walks. Qloo requests in the measured run: 972 live, the rest from the on-disk cache.

## Per site (top picks)

Qloo and OSM are the places of that kind inside the 10-minute walk ('+' = Qloo's cap of 100; OSM 'n/a' = no OpenStreetMap tag reliably marks that kind). Supply is relative supply: places inside the walk against what the surrounding 20-minute walk predicts (1.00 = typical). Rank is where people here rank that place type (1 = most engaged; '>50' = outside their top 50).

| # | Storefront | Model | Chatbot's top pick, as written | Qloo genre | Qloo | OSM | Supply | Rank | Walk-in's pick | Qloo | OSM | Supply | Rank |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Milwaukee Ave, Wicker Park, Chicago | 3.6-flash | Curated Vintage & Apparel Boutique | Vintage clothing store | 4 | n/a | 1.34 | >50 | Lounge | 0 | 0 | 0.45 | 4 |
| 2 | 37th Ave, Jackson Heights, New York | 3.6-flash | Specialty Grocery & Gourmet Deli | Deli | 2 | 9 | 0.79 | >50 | Japanese | 2 | 3 | 0.59 | 4 |
| 3 | South Congress Ave, Austin | 3.6-flash | Boutique Apparel & Lifestyle Retail | Clothing store | 3 | 9 | 1.43 | >50 | Tex-Mex | 2 | 1 | 1.07 | 1 |
| 4 | Cesar E Chavez Ave, Boyle Heights, Los Angeles | 3.6-flash | Specialty Cafe & Panadería | Cafe | 2 | 0 | 0.74 | 23 | Mexican | 17 | 6 | 1.00 | 5 |
| 5 | Av. Álvaro Obregón, Roma Norte, Mexico City | 3.6-flash | Specialty Coffee & Artisanal Bakery Concept | Coffee shop | 29 | 54 | 0.92 | 6 | Fast food restaurant | 7 | 19 | 0.46 | 8 |
| 6 | Upper Street, Islington, London | 3.6-flash | Artisan Bakery & Specialty Cafe | Bakery | 12 | 13 | 1.03 | >50 | Pub | 27 | 34 | 0.96 | 2 |
| 7 | Rue Oberkampf, 11e, Paris | 3.6-flash | All-Day Specialty Cafe & Natural Wine Bar | Cafe | 19 | 114 | 0.92 | 5 | Brunch | 10 | 1 | 0.67 | 8 |
| 8 | Karl-Marx-Straße, Neukölln, Berlin | 3.6-flash | Specialty Coffee Shop & Artisan Bakery | Coffee shop | 9 | 44 | 1.00 | 8 | Cultural center | 1 | n/a | 1.05 | 1 |
| 9 | Calle de Fuencarral, Malasaña, Madrid | 3.6-flash | Specialty Coffee & Artisanal Bakery | Coffee shop | 45 | 107 | 1.14 | 16 | Tapas | 18 | 9 | 0.63 | 8 |
| 10 | Road 9, Maadi, Cairo | 3.6-flash | Specialty Coffeehouse & Artisanal Bakery | Coffee shop | 6 | 11 | 1.00 | 2 | Cafe | 17 | 12 | 1.07 | 1 |
| 11 | Joo Chiat Road, Singapore | 3.6-flash | Specialty Artisanal Bakery & Cafe | Bakery | 8 | 15 | 1.49 | 27 | Chinese | 2 | 5 | 0.44 | 7 |
| 12 | Togoshi Ginza shopping street, Tokyo | 3.5-flash | Specialty Takeaway Food & Beverage Stand | Takeout Restaurant | 14 | n/a | 1.73 | 12 | Modern izakaya restaurant | 0 | n/a | 0.41 | 2 |
| 13 | King Street, Newtown, Sydney | 2.5-flash | Modern Plant Shop & Homewares | Plant Nursery | 0 | n/a | 0.48 | >50 | Lunch restaurant | 11 | n/a | 1.00 | 5 |
| 14 | Sydney Road, Brunswick, Melbourne | 2.5-flash | Specialty Bakery & Coffee Shop | Bakery | 4 | 10 | 0.92 | 29 | Pub | 10 | 17 | 1.14 | 1 |
| 15 | Honduras, Palermo Soho, Buenos Aires | 2.5-flash | Specialty Coffee & Brunch Cafe | Coffee shop | 18 | 71 | 0.89 | 14 | Argentinian restaurant | 8 | 9 | 0.89 | 2 |

## Sensitivity

- **Least-crowded reading.** Reading each compound chatbot pick as whichever named business has the fewest competitors (a bakery rather than a coffee shop, say), its median stays 8 on Qloo (9 sites to 5, p = 0.42) and 14 on OpenStreetMap; 33% (5/15) over-supplied; 27% (4/15) in people's top 15.
- **All three suggestions.** The chatbot's 45 suggestions (43 mappable to a Qloo genre) against Walk-in's top three gaps per site: median 4 vs 5 competitors on Qloo, 9.5 vs 3 on OpenStreetMap; over-supplied 26% (11/43) vs 7% (3/45); in people's top 15 23% (10/43) vs 100% (45/45).
- **The app's resolver alone.** `engine.find_genre` on the chatbot's wording as written mapped 0 of its 45 categories (compounds like 'Specialty Coffee & Artisanal Bakery Concept' match no Qloo genre), hence the component rule in the method.

## Alternatives (secondary)

| # | City | Chatbot's alternatives → Qloo genre (Qloo / OSM / supply / rank) | Walk-in's 2nd and 3rd gaps (Qloo / OSM / supply / rank) |
|---|---|---|---|
| 1 | Chicago | Specialty Coffee & Artisanal Bakery → Coffee shop (15 / 15 / 1.12 / 9); Independent Vinyl & Concept Bookstore → Record store (3 / 5 / 1.34 / >50) | Live music venue (4 / 0 / 0.89 / 1); Sports Bar (3 / 0 / 0.76 / 5) |
| 2 | New York | Specialty Coffee Shop & Bakery → Coffee shop (12 / 13 / 1.23 / 15); Boutique Health & Wellness Store → Vitamin & supplements store (2 / n/a / 1.03 / >50) | Asian (5 / 18 / 0.71 / 5); Brunch (4 / 0 / 1.08 / 1) |
| 3 | Austin | Specialty Coffee & All-Day Cafe → Coffee shop (7 / 7 / 1.03 / 13); Experiential Local Gift & Vintage Shop → Gift shop (3 / 1 / 1.43 / 21) | Brunch (3 / 0 / 1.24 / 2); Mexican (3 / 5 / 0.65 / 5) |
| 4 | Los Angeles | Fresh Juice & Health Food Bar → Juice shop (0 / 0 / 0.41 / >50); Neighborhood Plant Shop & Artisan Market → Plant Nursery (0 / n/a / 0.53 / >50) | Basketball court (0 / n/a / 0.53 / 2); Ice hockey rink (0 / n/a / 0.53 / 1) |
| 5 | Mexico City | Boutique Natural Wine Bar & Small Plates → Wine Bar (5 / 0 / 1.30 / >50); Curated Design & Sustainable Fashion Concept Store → Clothing store (5 / 12 / 0.76 / 28) | Cafeteria (16 / n/a / 1.03 / 5); Bar + Grill (18 / n/a / 1.01 / 3) |
| 6 | London | Boutique Wine Shop & Tapas Bar → Wine store (7 / 2 / 1.17 / >50); Sustainable Lifestyle & Home Decor Boutique → (no Qloo genre) | Live music venue (4 / 3 / 0.79 / 4); British (5 / 1 / 1.22 / 3) |
| 7 | Paris | Artisan Bakery & Gourmet Sandwich Shop → Bakery (18 / 50 / 1.04 / 22); Sustainable Vintage & Lifestyle Concept Store → Vintage clothing store (0 / n/a / 0.71 / >50) | Bistro (24 / 0 / 0.86 / 2); French (48 / 32 / 1.11 / 1) |
| 8 | Berlin | Vintage Clothing & Sustainable Lifestyle Concept Store → Vintage clothing store (0 / n/a / 0.93 / >50); Fast-Casual Asian Fusion Street Food Restaurant → Street Food (0 / n/a / 0.93 / >50) | Live music venue (1 / 2 / 0.91 / 3); Cocktail Bar (4 / 1 / 0.78 / 6) |
| 9 | Madrid | Sustainable Streetwear Concept Store → Clothing store (24 / 210 / 0.98 / >50); Clean Beauty & Niche Cosmetics Boutique → Cosmetics store (10 / 15 / 1.17 / >50) | Tapas bar (49 / 9 / 0.96 / 1); Cocktail Bar (49 / 0 / 1.04 / 2) |
| 10 | Cairo | Boutique Pilates & Wellness Studio → Pilates studio (1 / 0 / 1.05 / >50); Concept Bookstore & Specialty Tea Bar → Book store (0 / 1 / 0.52 / >50) | Coffee shop (6 / 11 / 1.00 / 2); Breakfast (2 / 0 / 1.09 / 5) |
| 11 | Singapore | Boutique Pilates & Wellness Studio → Pilates studio (0 / 0 / 0.90 / >50); Independent Home Decor & Gift Store → Gift shop (1 / 3 / 1.42 / >50) | Singaporean restaurant (3 / 0 / 1.00 / 1); Western restaurant (4 / n/a / 1.75 / 5) |
| 12 | Tokyo | Specialty Neighborhood Coffee & Bakery Shop → Coffee shop (8 / 6 / 1.62 / 9); Curated Japanese Lifestyle & Everyday Goods Store → (no Qloo genre) | Izakaya restaurant (8 / 0 / 0.92 / 1); Ramen restaurant (7 / 3 / 1.08 / 3) |
| 13 | Sydney | independent bookstore → Book store (2 / 3 / 0.94 / >50); gender-neutral hair salon and barber shop → Hair salon (2 / 10 / 0.94 / >50) | Cafe (30 / 34 / 0.75 / 8); Coffee shop (24 / 29 / 0.86 / 6) |
| 14 | Melbourne | Independent Bookstore & Community Hub → Book store (1 / 2 / 0.90 / >50); Curated Vintage & Artisanal Homewares Store → Vintage clothing store (0 / n/a / 0.56 / >50) | Cocktail Bar (4 / 0 / 1.00 / 3); Wine Bar (2 / 0 / 0.55 / 6) |
| 15 | Buenos Aires | Curated Independent Fashion Boutique → Clothing store (18 / 82 / 0.96 / 25); Artisan Cocktail Bar & Small Plates → Cocktail Bar (11 / 1 / 1.24 / 16) | Disco club (4 / 7 / 0.78 / 4); Personal care (10 / 4 / 0.63 / 5) |

## Method

1. **Sites:** 15 storefront addresses on commercial streets in 15 cities on 6 continents (trendy strips, immigrant and working-class high streets, a Tokyo shotengai, a Cairo road), geocoded with Nominatim and fixed before any result was seen.
2. **Chatbot:** one call per site with the app's LLM settings (Gemini via its OpenAI-compatible endpoint, reasoning effort low, next fallback model on a 429 or 503), no system prompt, the prompt verbatim; top pick and two alternatives parsed from the reply.
3. **Walk-in, no LLM:** the 10-minute walk from Valhalla, Qloo's genre ranking for it (`engine.demand_genres`) and the Qloo-only gap table (`engine.gap_table(..., 'any', None)`); its pick is the top row.
4. **Same measure:** each business a chatbot category names ('Specialty Coffee & Artisanal Bakery' names two) was mapped to a Qloo genre through a fixed keyword table of Qloo genre names, resolved with `engine.find_genre`, and measured with `engine.probe_genre` on the table's own supply baseline; the first-named one counts.
5. **Independent check:** OpenStreetMap's named places of each kind inside the same walk (`OsmClient.scan` plus `CrossCheck.places_of`), retried over several rounds and Overpass instances; no walk was left unchecked.
6. **Metrics:** (a) distinct top picks; (b) median competitors inside the walk on Qloo and OpenStreetMap, with a paired sign test; (c) share over-supplied (≥ 1.2) or under-supplied (≤ 0.8); (d) share in people's top 15.

## Caveats

- **(b) to (d) use Walk-in's own data (Qloo) for both sides.** OpenStreetMap is the independent check, and it is skewed here: a café is tagged the same way everywhere, cuisine-level kinds often are not, so it undercounts many of Walk-in's picks (and has no tag at all for some of each side's: Vintage clothing store, Takeout, Plant nursery, Cultural center, Modern izakaya, Lunch restaurant). Most walks were read from an instance whose data dates from August 2026.
- **Walk-in is partly graded on its own objective.** It only considers the place types people here rank in their top 8, so (d) is 100% by construction, and its score favours low relative supply, so (c) leans its way. (a) and the OpenStreetMap counts are the parts it was not built to win.
- **15 sites is small.** One chatbot answer per site, and a second could differ; 4 of 15 came from fallback models after HTTP 503 (overloaded) errors. No difference in (b) is statistically significant.
- **The chatbot had no map.** That is the point being tested, not a flaw: it is what anyone gets by asking a chatbot about an address.
- **Taste data isn't foot traffic or sales.** Neither side's pick was checked against footfall, rents or revenue, and a gap is not proof of demand.
- **Mapping is a judgment.** Compound picks were read as their first-named business (the least-crowded reading is in the sensitivity section); kinds Qloo has no place genre for (groceries, home decor, concept stores) count as unmapped. Breadth matters too: 'Coffee shop' is common everywhere, so raw counts partly measure how broad a category is.
- **This is the gap table, not the whole app.** The live survey also folds OpenStreetMap places into supply and has the AI turn the top gaps into concepts; neither step ran here. The raw top row is not always a storefront business (Berlin's is 'Cultural center').

## Files

- `sites.json`: the 15 storefronts with the geocoder's confirmation.
- `results.json`: per site, the chatbot's raw answer and model, the parsed picks, every business each pick names with its mapping, both sides' numbers, Walk-in's gap table and the OpenStreetMap counts; the aggregate metrics. It holds numbers worked out from Qloo's answers and Qloo's place-type names, not Qloo's answers themselves; the names of places in it come from OpenStreetMap (© OpenStreetMap contributors, ODbL).
- `run_h2h.py`: the script (phases sites, chat, data, osm, report), run from the repository root. It writes this report as `report.md`. It keeps the chatbot's answers and the per-site measurements it reuses in `_cache/`, which is not published: the hackathon's rules forbid publishing cached Qloo data.
