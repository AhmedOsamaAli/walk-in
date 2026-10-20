"""Run the full survey pipeline for the preset sites and print a compact report for review.

Usage: python scripts/evaluate_sites.py [site_id ...] [--minutes 10] [--focus any]
Responses are cached in .cache/ (gitignored); nothing from Qloo is written to the repository.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import agent  # noqa: E402
from app.catchment import CatchmentService  # noqa: E402
from app.config import settings  # noqa: E402
from app.main import PRESETS  # noqa: E402
from app.providers import build_llm  # noqa: E402
from app.qloo import QlooClient  # noqa: E402


def print_report(run: agent.RunState, events: list[tuple[str, dict]]) -> None:
    done = next((data for event, data in events if event == "done"), {})
    walk = run.catchment
    print(f"\n{'=' * 88}\n{run.site.label}  ({run.site.minutes}-min walk, focus={run.site.focus})")
    if walk:
        print(f"walk: {walk.source}, {walk.area_m2 / 1e6:.2f} km², equivalent radius {walk.radius_m:.0f} m")
    print(f"run: {done.get('seconds')} s, {done.get('qloo_calls')} Qloo calls, {done.get('cache_hits')} cached")
    s = run.summary
    print(f"block: {s.get('place_count')} places | avg rating {s.get('avg_rating')} | prices {s.get('price_levels')}")
    print("  common:", ", ".join(f"{g} {n}" for g, n in s.get("top_genres", [])[:6]))
    print("  praise:", ", ".join(k for k, _ in s.get("praise", [])[:6]))
    print("  complaints:", ", ".join(k for k, _ in s.get("complaints", [])[:6]) or "-")
    print("gaps:")
    for row in run.gaps[:6]:
        print(
            f"  {row['gap_score']:>3} {row['genre']:<24} #{row['demand_rank']} here/#{row['ref_rank'] if row['ref_rank'] is not None else '-'} around"
            f" | inside {row['nearby_count']}{'+' if row['nearby_capped'] else ''} vs ~{row['expected_nearby']} typical"
            f" (rel {row['relative_supply']}) | {row['favorites_kind']} favorites outside {row['favorites_far']}/{row['favorites_total']}"
            f"{'' if row['evidence'] == 'ok' else ' | ' + row['evidence'].upper()}"
        )
    print("concepts:")
    for concept in run.concepts:
        print(f"  - {concept['name']} [{concept['genre']}, gap {concept['gap_score']}] {concept.get('one_liner')}")
        print(f"    signature: {', '.join(concept.get('signature') or []) or '-'} | inspired by: {', '.join(concept.get('inspired_by') or []) or '-'}")
    taste = run.taste
    print("taste: brands", ", ".join(b["name"] for b in taste.get("distinctive_brands", [])[:6]) or "-")
    print("       artists", ", ".join(a["name"] for a in taste.get("distinctive_artists", [])[:6]) or "-")
    print("       crowd", agent.describe_age(run.demographics), "| cues:", ", ".join(run.cues) or "-")
    for event, data in events:
        if event in ("error", "notice"):
            print(f"  {event.upper()}: {data.get('message')}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("sites", nargs="*", help="preset ids (default: all)")
    parser.add_argument("--minutes", type=int, default=10)
    parser.add_argument("--focus", default="any")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    qloo = QlooClient(settings.qloo_api_key, settings.qloo_base_url, settings.cache_dir)
    walker = CatchmentService(settings.walk_cache_dir)
    llm = build_llm(settings)
    store = agent.RunStore()
    try:
        for preset in PRESETS:
            if args.sites and preset["id"] not in args.sites:
                continue
            events: list[tuple[str, dict]] = []

            async def emit(event: str, data: dict) -> None:
                events.append((event, data))

            site = agent.Site(preset["lat"], preset["lon"], preset["label"], args.focus, "", args.minutes)
            run = await agent.analyze_site(qloo, walker, llm, store, site, emit)
            print_report(run, events)
    finally:
        await qloo.aclose()
        await walker.aclose()


if __name__ == "__main__":
    asyncio.run(main())
