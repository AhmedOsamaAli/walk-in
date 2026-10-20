"""Day-1 validation of Qloo hackathon data for the Blank Space idea.

Answers five questions before anything gets built:
  1. Supply: does Qloo know the places around a site (Cairo vs Dubai vs NYC), with review keywords?
  2. Fingerprint: does a location signal change taste analysis (urn:tag) between neighborhoods?
  3. Media/brands: does a location signal change artist and brand results, citywide and
     between Cairo neighborhoods?
  4. Heatmaps: how dense is the signal in Cairo compared with Dubai and New York?
  5. Coverage: are well-known Cairo places in Qloo, and do they carry demographics?

Raw responses are cached in .cache/validation/ (gitignored). Never commit Qloo data.
Usage: python scripts/validate_qloo.py [--refresh]
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "validation"
REFRESH = "--refresh" in sys.argv
RADIUS_M = 800  # roughly a 10-minute walk

# (label, latitude, longitude)
SITES = {
    "cairo_zamalek": ("Zamalek, Cairo", 30.0626, 31.2197),
    "cairo_imbaba": ("Imbaba, Giza", 30.0830, 31.2010),
    "cairo_downtown": ("Downtown Cairo (Talaat Harb)", 30.0486, 31.2400),
    "cairo_maadi": ("Maadi (Road 9)", 29.9603, 31.2590),
    "cairo_newcairo": ("New Cairo (90th Street)", 30.0245, 31.4785),
    "dubai_downtown": ("Downtown Dubai", 25.1972, 55.2744),
    "nyc_williamsburg": ("Williamsburg, Brooklyn", 40.7145, -73.9580),
    "nyc_ues": ("Upper East Side, Manhattan", 40.7736, -73.9566),
}

KNOWN_CAIRO_PLACES = [
    ("Cafe Riche", 30.0486, 31.2400),
    ("Abou Tarek", 30.0486, 31.2400),
    ("Zooba", 30.0626, 31.2197),
    ("Diwan Bookstore", 30.0626, 31.2197),
    ("Cairo Festival City Mall", 30.0287, 31.4086),
]

DESCRIPTION_KEYS = (
    "overall_description",
    "customer_demographics_description",
    "ambience_description",
    "unique_selling_points",
)


def load_env() -> tuple[str, str]:
    env_file = ROOT / ".env"
    if env_file.exists():
        for raw in env_file.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    api_key = os.environ.get("QLOO_API_KEY", "").strip()
    base_url = os.environ.get("QLOO_BASE_URL", "https://hackathon.api.qloo.com").strip().rstrip("/")
    if not api_key:
        sys.exit("QLOO_API_KEY is empty. Paste your key into .env (QLOO_API_KEY=...) and rerun.")
    return api_key, base_url


API_KEY, BASE_URL = load_env()
STATS: Counter = Counter()


def call(label: str, path: str, params: dict) -> dict:
    """GET a Qloo endpoint, caching successful responses on disk."""
    cache_file = CACHE / f"{label}.json"
    if cache_file.exists() and not REFRESH:
        STATS["cached"] += 1
        return json.loads(cache_file.read_text(encoding="utf-8"))
    query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    request = urllib.request.Request(
        f"{BASE_URL}{path}?{query}",
        headers={"X-Api-Key": API_KEY, "Accept": "application/json"},
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                data = json.loads(response.read().decode("utf-8"))
            STATS["ok"] += 1
            CACHE.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            time.sleep(0.3)
            return data
        except urllib.error.HTTPError as error:
            if error.code == 429 and attempt < 3:
                time.sleep(3 * (attempt + 1))
                continue
            STATS[f"http_{error.code}"] += 1
            return {"_error": error.code, "_body": error.read().decode("utf-8", "replace")[:300]}
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt < 3:
                time.sleep(3)
                continue
            STATS["network_error"] += 1
            return {"_error": "network", "_body": str(error)}
    return {"_error": "retries_exhausted", "_body": ""}


def error_of(data: dict) -> str | None:
    if "_error" in data:
        return f"ERROR {data['_error']}: {data.get('_body', '')[:200]}"
    return None


def point(lat: float, lon: float) -> str:
    return f"POINT({lon} {lat})"  # WKT is longitude first


def insights_items(data: dict, key: str) -> list:
    results = data.get("results")
    return (results.get(key) or []) if isinstance(results, dict) else []


def search_items(data: dict) -> list:
    results = data.get("results")
    if isinstance(results, list):
        return results
    if isinstance(results, dict):
        return results.get("entities") or []
    return []


def item_id(item: dict) -> str | None:
    return item.get("entity_id") or item.get("tag_id") or item.get("id")


def resolved_locality(data: dict) -> str | None:
    found = (data.get("query") or {}).get("localities")
    if isinstance(found, list):
        found = found[0] if found else None
    if isinstance(found, dict) and isinstance(found.get("filter"), (dict, list)):
        found = found["filter"]
        if isinstance(found, list):
            found = found[0] if found else None
    if isinstance(found, dict):
        return found.get("disambiguation") or found.get("name")
    return None


def jaccard(a: list, b: list) -> float:
    sa, sb = set(a), set(b)
    return round(len(sa & sb) / len(sa | sb), 2) if sa | sb else 1.0


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def section(title: str) -> None:
    print(f"\n{'=' * 80}\n{title}\n{'=' * 80}")


def check_connectivity() -> str | None:
    section("0. Connectivity")
    data = call("search_starbucks", "/search", {"query": "Starbucks", "types": "urn:entity:brand", "take": 3})
    if error_of(data):
        sys.exit(f"Connectivity/auth failed -> {error_of(data)}")
    starbucks = next((e for e in search_items(data) if "starbucks" in (e.get("name") or "").lower()), None)
    print(f"OK: /search works. Starbucks brand id: {item_id(starbucks) if starbucks else 'not found'}")
    return item_id(starbucks) if starbucks else None


def scan_supply() -> dict:
    section(f"1. Places Qloo knows around each site (within {RADIUS_M} m)")
    supply = {}
    for slug, (name, lat, lon) in SITES.items():
        data = call(f"places_{slug}", "/v2/insights", {
            "filter.type": "urn:entity:place",
            "filter.location": point(lat, lon),
            "filter.location.radius": RADIUS_M,
            "take": 50,
        })
        if error_of(data):
            print(f"\n{name}: {error_of(data)}")
            continue
        places = insights_items(data, "entities")
        supply[slug] = places
        count = len(places)

        def share(subset: list) -> str:
            return f"{round(100 * len(subset) / count)}%" if count else "-"

        props = [(p, p.get("properties") or {}) for p in places]
        with_keywords = [pr for _, pr in props if pr.get("keywords")]
        with_desc = [pr for _, pr in props if any(pr.get(k) for k in DESCRIPTION_KEYS)]
        with_rating = [pr for _, pr in props if pr.get("business_rating")]
        with_price = [pr for _, pr in props if pr.get("price_level")]
        growth = [((p.get("query") or {}).get("measurements") or {}).get("audience_growth") for p in places]
        growth_moving = [g for g in growth if g not in (None, 0)]
        categories = Counter(
            tag.get("name")
            for p in places
            for tag in (p.get("tags") or [])
            if (tag.get("type") or "").startswith(("urn:tag:category:place", "urn:tag:genre:place"))
        )
        print(
            f"\n{name}: {count} places | review keywords {share(with_keywords)} | descriptions {share(with_desc)}"
            f" | rating {share(with_rating)} | price {share(with_price)} | audience_growth moving: {len(growth_moving)}"
        )
        mentions = [sum(k.get("count") or 0 for k in pr["keywords"]) for pr in with_keywords]
        if mentions:
            print(f"   keyword mentions per place: median {median(mentions)}, max {max(mentions)}")
        print("   top categories:", ", ".join(f"{c} ({n})" for c, n in categories.most_common(10)) or "-")
        for place, pr in props[:8]:
            keywords = ", ".join(k.get("name") for k in (pr.get("keywords") or [])[:4])
            print(f"   - {place.get('name')} | rating {pr.get('business_rating')} | {keywords}")
    return supply


def test_tag_fingerprint() -> None:
    section("2. Does a location signal change taste analysis (urn:tag, place genres)?")
    common = {"filter.type": "urn:tag", "filter.tag.types": "urn:tag:genre:place", "take": 25}
    baseline = call("tags_baseline", "/v2/insights", common)
    if error_of(baseline):
        print(f"baseline: {error_of(baseline)}")
    base_ids = [item_id(t) for t in insights_items(baseline, "tags")]
    print(f"baseline (no location): {len(base_ids)} tags ->", ", ".join(t.get("name") for t in insights_items(baseline, "tags")[:8]))

    per_site = {}
    for slug, (name, lat, lon) in SITES.items():
        data = call(f"tags_{slug}", "/v2/insights", {
            **common,
            "signal.location": point(lat, lon),
            "signal.location.radius": RADIUS_M,
        })
        if error_of(data):
            print(f"{name}: {error_of(data)}")
            continue
        tags = insights_items(data, "tags")
        per_site[slug] = [item_id(t) for t in tags]
        print(f"{name}: overlap with baseline {jaccard(per_site[slug], base_ids)} ->",
              ", ".join(t.get("name") for t in tags[:8]))

    query_test = call("tags_query_zamalek", "/v2/insights", {**common, "signal.location.query": "Zamalek"})
    if not error_of(query_test):
        q_ids = [item_id(t) for t in insights_items(query_test, "tags")]
        print(f"signal.location.query=Zamalek: overlap with POINT version {jaccard(q_ids, per_site.get('cairo_zamalek', []))}")

    slugs = list(per_site)
    pairs = [jaccard(per_site[a], per_site[b]) for i, a in enumerate(slugs) for b in slugs[i + 1:]]
    if pairs:
        print(f"\nAverage overlap between different sites: {round(sum(pairs) / len(pairs), 2)} (1.0 = location ignored)")
    if "cairo_zamalek" in per_site and "cairo_imbaba" in per_site:
        print(f"Zamalek vs Imbaba overlap: {jaccard(per_site['cairo_zamalek'], per_site['cairo_imbaba'])}")


def test_media_location() -> None:
    section("3. Does a location signal change artist and brand results?")
    locations = {
        "none": {},
        "cairo_query": {"signal.location.query": "Cairo"},
        "cairo_point": {"signal.location": point(30.0626, 31.2197), "signal.location.radius": 5000},
        "dubai_query": {"signal.location.query": "Dubai"},
        "nyc_query": {"signal.location.query": "New York"},
    }
    for entity_type in ("urn:entity:artist", "urn:entity:brand"):
        short = entity_type.rsplit(":", 1)[-1]
        runs = {}
        for loc_label, loc_params in locations.items():
            data = call(f"{short}_{loc_label}", "/v2/insights", {
                "filter.type": entity_type,
                "filter.popularity.min": 0.1,
                "take": 20,
                **loc_params,
            })
            if error_of(data):
                print(f"{short} / {loc_label}: {error_of(data)}")
                continue
            runs[loc_label] = insights_items(data, "entities")
        if "none" not in runs:
            continue
        none_ids = [item_id(e) for e in runs["none"]]
        print(f"\n{short}s, no location:", ", ".join(e.get("name") for e in runs["none"][:8]))
        for loc_label, entities in runs.items():
            if loc_label == "none":
                continue
            print(f"{short}s, {loc_label}: overlap with no-location {jaccard([item_id(e) for e in entities], none_ids)} ->",
                  ", ".join(e.get("name") for e in entities[:8]))


def test_neighborhood_taste() -> None:
    section("3b. Do brand and artist tastes differ between Cairo neighborhoods (1.5 km)?")
    cairo_sites = {slug: site for slug, site in SITES.items() if slug.startswith("cairo_")}
    for entity_type in ("urn:entity:brand", "urn:entity:artist"):
        short = entity_type.rsplit(":", 1)[-1]
        common = {"filter.type": entity_type, "filter.popularity.min": 0.1, "take": 20}
        citywide = call(f"{short}_cairo_query", "/v2/insights", {**common, "signal.location.query": "Cairo"})
        city_ids = {item_id(e) for e in insights_items(citywide, "entities")}
        lists = {}
        for slug, (name, lat, lon) in cairo_sites.items():
            data = call(f"{short}_hood_{slug}", "/v2/insights", {
                **common,
                "signal.location": point(lat, lon),
                "signal.location.radius": 1500,
            })
            if error_of(data):
                print(f"{short} / {name}: {error_of(data)}")
                continue
            entities = insights_items(data, "entities")
            lists[slug] = [item_id(e) for e in entities]
            distinctive = [e.get("name") for e in entities if item_id(e) not in city_ids]
            print(f"\n{short}s near {name}:", ", ".join(e.get("name") for e in entities[:8]))
            print(f"   not in Cairo-wide top 20: {', '.join(distinctive[:8]) or '-'}")
        slugs = list(lists)
        pairs = {f"{a.split('_', 1)[1]} vs {b.split('_', 1)[1]}": jaccard(lists[a], lists[b])
                 for i, a in enumerate(slugs) for b in slugs[i + 1:]}
        if pairs:
            print(f"\n{short} overlap between neighborhoods:", ", ".join(f"{k} {v}" for k, v in pairs.items()))
            print(f"average: {round(sum(pairs.values()) / len(pairs), 2)} (1.0 = identical)")


def pick_cafe_tag(supply: dict) -> tuple[str, str] | None:
    for slug in ("cairo_zamalek", "cairo_newcairo", "cairo_maadi"):
        for place in supply.get(slug, []):
            for tag in place.get("tags") or []:
                name = (tag.get("name") or "").lower()
                if ("coffee" in name or "cafe" in name) and tag.get("id"):
                    return tag["id"], tag.get("name")
    return None


def test_heatmaps(starbucks_id: str | None, supply: dict) -> None:
    section("4. Heatmap density: Cairo vs Dubai vs New York")
    probes = []
    if starbucks_id:
        probes.append(("starbucks", {"signal.interests.entities": starbucks_id}))
    cafe = pick_cafe_tag(supply)
    if cafe:
        probes.append((f"tag_{slugify(cafe[1])}", {"signal.interests.tags": cafe[0]}))
    for probe_label, probe_params in probes:
        print(f"\nProbe: {probe_label}")
        for city in ("Cairo", "Dubai", "New York"):
            data = call(f"heatmap_{probe_label}_{slugify(city)}", "/v2/insights", {
                "filter.type": "urn:heatmap",
                "filter.location.query": city,
                **probe_params,
            })
            if error_of(data):
                print(f"  {city}: {error_of(data)}")
                continue
            cells = insights_items(data, "heatmap")
            resolved = resolved_locality(data)
            affinity = [c["query"]["affinity"] for c in cells if c.get("query")]
            popularity = [c["query"]["popularity"] for c in cells if c.get("query")]
            stats = (f"affinity median {median(affinity):.2f} | popularity median {median(popularity):.2f}"
                     if affinity else "no cells")
            print(f"  {city} (resolved: {resolved}): {len(cells)} cells | {stats}")


def test_known_places(supply: dict) -> None:
    section("5. Are well-known Cairo places in Qloo?")
    for query, lat, lon in KNOWN_CAIRO_PLACES:
        data = call(f"search_place_{slugify(query)}", "/search", {
            "query": query,
            "types": "urn:entity:place",
            "filter.location": f"{lat},{lon}",
            "filter.radius": 5,
            "take": 3,
        })
        if error_of(data):
            print(f"{query}: {error_of(data)}")
            continue
        hits = search_items(data)
        if hits:
            top = hits[0]
            props = top.get("properties") or {}
            print(f"{query}: FOUND '{top.get('name')}' | {str(props.get('address'))[:60]} | rating {props.get('business_rating')}"
                  f" | keywords {len(props.get('keywords') or [])}")
        else:
            print(f"{query}: not found")

    sample = (supply.get("cairo_zamalek") or supply.get("cairo_downtown") or [None])[0]
    if sample:
        data = call("demographics_cairo_sample", "/v2/insights", {
            "filter.type": "urn:demographics",
            "signal.interests.entities": item_id(sample),
        })
        rows = insights_items(data, "demographics")
        if error_of(data) or not rows:
            print(f"\nDemographics for '{sample.get('name')}': {error_of(data) or 'no data'}")
        else:
            print(f"\nDemographics for '{sample.get('name')}':", json.dumps(rows[0].get("query"))[:300])


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    starbucks_id = check_connectivity()
    supply = scan_supply()
    test_tag_fingerprint()
    test_media_location()
    test_neighborhood_taste()
    test_heatmaps(starbucks_id, supply)
    test_known_places(supply)
    section("Run stats")
    print(dict(STATS))


if __name__ == "__main__":
    main()
