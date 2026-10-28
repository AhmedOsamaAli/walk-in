"""Hot spots made faster must answer exactly as before: each is checked against the code it replaced, kept here as the
reference, over many inputs."""
from __future__ import annotations

import math
import random
import re

from app import catchment, scoring


def douglas_peucker_before(points, tolerance):
    """The simplification as it ran before: once per tolerance tried."""
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        (x1, y1), (x2, y2) = points[first], points[last]
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy)
        worst, index = 0.0, None
        for i in range(first + 1, last):
            px, py = points[i]
            d = abs(dy * px - dx * py + x2 * y1 - y2 * x1) / norm if norm else math.hypot(px - x1, py - y1)
            if d > worst:
                worst, index = d, i
        if index is not None and worst > tolerance:
            keep[index] = True
            stack += [(first, index), (index, last)]
    return [p for p, k in zip(points, keep, strict=True) if k]


def simplify_before(ring, max_points=catchment.QLOO_RING_POINTS):
    if len(ring) <= max_points:
        return ring
    tolerance = 1e-5
    while True:
        kept = douglas_peucker_before(ring, tolerance)
        if len(kept) <= max_points:
            return kept if kept[0] == kept[-1] else kept + [kept[0]]
        tolerance *= 1.6


def outline(seed: int, points: int, closed: bool = True) -> list[tuple[float, float]]:
    """A wobbly outline like a walk's or a drive's: a circle whose radius wanders, with some points repeated."""
    rng = random.Random(seed)
    radius, ring = 0.02, []
    for i in range(points):
        radius = max(0.002, radius + rng.uniform(-0.002, 0.002))
        angle = 2 * math.pi * i / points
        ring.append((round(30.26 + radius * math.cos(angle), 6), round(-97.72 + radius * math.sin(angle), 6)))
        if rng.random() < 0.02:
            ring.append(ring[-1])  # a repeated point, as routing engines sometimes return
    return ring + [ring[0]] if closed else ring


def test_the_outline_is_simplified_to_the_same_points_as_before():
    for seed in range(40):
        ring = outline(seed, random.Random(seed).choice([150, 181, 400, 1200, 3000]), closed=seed % 7 != 0)
        for max_points in (10, 60, catchment.QLOO_RING_POINTS, 500):
            assert catchment.simplify_ring(ring, max_points) == simplify_before(ring, max_points), (seed, max_points)
    straight = [(30.0 + i * 1e-4, -97.0) for i in range(400)]  # nothing off the line: only the ends stay
    assert catchment.simplify_ring(straight) == simplify_before(straight)


def repeats_before(keyword: str, own: str) -> bool:
    words = re.sub(r"^(el|al|the) ", "", scoring._fold(keyword.strip()))
    return bool(re.search(rf"(?<!\w){re.escape(words)}(?!\w)", own))


def test_a_keyword_that_repeats_the_place_s_own_words_is_found_as_before():
    owns = ["zamalek 26 july street zamalek", "katz's delicatessen 205 e houston st", "steak house 1 main st",
            "café riche 17 talaat harb", "the tea room", "o'reilly's pub", "bar_none 12 north", "", "a b c",
            "kebab-house #2, ü-bahn", "مطعم القاهرة 5 شارع", "tea tea", "x"]
    keywords = ["zamalek", "el zamalek", "the zamalek", "katz", "Katz's", "tea", "Tea Room", "steak", "house", "riche",
                "café", "cafe", "pub", "o", "reilly", "bar", "none", "bar_none", "kebab", "house #2", "ü", "bahn",
                "القاهرة", "شارع", "a", "b c", "", " ", "the ", "al ", "tea tea", "ea", "x", "12", "2"]
    for own in owns:
        for keyword in keywords:
            assert scoring._repeats(keyword, own) == repeats_before(keyword, own), (keyword, own)


def test_keyword_lists_match_as_one_pattern_per_word_did():
    """The keyword lists are matched with one pattern each, compiled once; before, every word of every list was turned
    into a pattern on every call. Both must find exactly the same."""

    def per_word(text: str, words, plural: str) -> bool:
        return any(re.search(rf"\b{re.escape(word)}{plural}\b", text) for word in words)

    lists = [*scoring.FOCUS_KEYWORDS.values(), scoring.RETAIL_GOODS, scoring.VENUE_WORDS, scoring.BAR_WORDS,
             scoring.WELLNESS_WORDS, scoring.STOREFRONT_VENUE_WORDS]
    words = sorted({word for words in lists for word in words})
    texts = {"", "Restaurant", "Barbershop", "Barbecue", "Bars", "Bar & Grill", "Bar + Grill", "Wine bar", "Wine shops",
             "Sports bar", "Tex-Mex", "Tex-Mexes", "Café", "Cafés", "Cafe-bar", "Pubs", "Pubes", "Spas", "Spaes",
             "Studio", "Yoga studio", "Pilates", "Nail salon", "Barber", "Barbers", "Barberes", "Coffee shop",
             "Ice cream shop", "Dessert shops", "Liquor store", "Health food store", "Deli shop", "Deli", "Delis",
             "Night club", "Nightclub", "Brewery", "Breweries", "Theater", "Theaters", "Concert hall", "Event venue",
             "Gastropub", "Karaoke bar", "Personal care", "Tattoo parlor", "Fast food", "BBQ", "Middle Eastern",
             "Shisha lounge", "Bookstore", "Book store", "Record shop", "Pet store", "Bike shop", "Thrift store",
             "Coworking space", "Bowling alley", "Climbing gym", "Arcade bar", "Dance studio", "Music venue"}
    for word in words:
        for form in (word, word + "s", word + "es", f"the {word} place", f"{word}y", f"x{word}", word.upper()):
            texts.add(form)
    for text in sorted(texts):
        lowered = text.lower()
        for words_list in lists:
            assert scoring._matches(text, words_list) == per_word(lowered, words_list, "(s|es)?"), (text, words_list[:3])
            assert scoring._has_word(lowered, words_list) == per_word(lowered, words_list, "s?"), (text, words_list[:3])
