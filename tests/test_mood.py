"""The mood board: which tiles it shows, the era their years point to, the direction that era maps to, the checks on
a model's statement, and what the render prompts may carry."""
from __future__ import annotations

import asyncio
import json
import re

import pytest
from fastapi.testclient import TestClient

from app.answers import AnswerCache
from app.images import ImageGen
from app.llm import LLM
from app.main import Services, create_app
from app.survey import design, mood, pipeline
from app.survey.models import RunState, RunStore, Site
from tests.fakes import SITE, FakeImages, FakeQloo, FakeWalker, StubGeocoder

IMG = "https://images.qloo.com/i/{}-420x-auto.jpg"


def card(name: str, **extra) -> dict:
    return {"id": f"id-{name}", "name": name, "image": IMG.format(re.sub(r"\W+", "-", name)), "popularity": 0.9, **extra}


def taste(artists=(), movies=(), tv=(), brands=(), **extra) -> dict:
    return {
        "distinctive_artists": list(artists), "distinctive_movies": list(movies), "distinctive_tv": list(tv),
        "distinctive_brands": list(brands), **extra,
    }


def run_with(data: dict, label: str = "Test Corner, Testville") -> RunState:
    run = RunState(id="r", site=Site(0, 0, label))
    run.taste = data
    return run


FULL = taste(
    artists=[card("Jazz Elder", since=1972), card("Soul Sister", since=1975), card("Disco Duo", since=1978)],
    movies=[card("Harbor Lights", year=1979), card("Night Ferry", year=1984), card("Dock Days", year=2019)],
    tv=[card("Pier Pressure", year=1981), card("Market Hours", year=1976)],
    brands=[card("Riverside Cider Co", kind="product"), card("Neighborhood Bikes", kind="retail")],
)


# ---------- Tiles ----------

def test_tiles_take_turns_across_kinds_and_keep_only_qloo_images():
    data = taste(
        artists=[card("Jazz Elder", since=1972), {**card("Elsewhere Image"), "image": "https://evil.test/a.jpg"},
                 {**card("No Image"), "image": None}, card("Soul Sister", since=1975), card("Disco Duo", since=1978)],
        movies=[card("Harbor Lights", year=1979), card("Night Ferry", year=1984), card("Dock Days", year=2019)],
        tv=[card("Pier Pressure", year=1981)],
        brands=[card("Riverside Cider Co", kind="product"), card("Neighborhood Bikes", kind="retail"), card("Tide Co")],
    )
    tiles = mood.pick_tiles(data)
    assert [t["kind"] for t in tiles] == ["artist", "film", "show", "brand", "artist", "film", "brand", "artist", "film"]
    assert tiles[0] == {"name": "Jazz Elder", "kind": "artist", "image": IMG.format("Jazz-Elder"), "since": 1972}
    assert tiles[1] == {"name": "Harbor Lights", "kind": "film", "image": IMG.format("Harbor-Lights"), "year": 1979}
    assert "year" not in tiles[3] and "since" not in tiles[3]
    assert not {"Elsewhere Image", "No Image"} & {t["name"] for t in tiles}
    assert all(t["image"].startswith("https://images.qloo.com/") for t in tiles)


def test_names_the_categorys_fans_share_come_first_when_qloo_used_the_category():
    fans = {"specific": True, "artists": [card("Disco Duo")], "brands": [card("Neighborhood Bikes")]}
    tiles = mood.pick_tiles(FULL, fans)
    assert [t["name"] for t in tiles[:4]] == ["Disco Duo", "Harbor Lights", "Pier Pressure", "Neighborhood Bikes"]
    ignored = {**fans, "specific": False}
    assert mood.pick_tiles(FULL, ignored)[0]["name"] == "Jazz Elder"


def test_a_short_board_fills_from_the_fans_then_from_what_people_here_rank_highest():
    thin = taste(artists=[card("Wegz", since=2017)], movies=[card("19B", year=2022)], brands=[card("Anghami", kind="media")])
    thin["artists"] = [card("Wegz"), card("Global Star", popularity=0.999), card("Local Legend", since=1983)]
    thin["brands"] = [card("Phone Network", kind="corporate"), card("Kojak Studio", kind="product")]

    fans = {"specific": True, "artists": [card("Fan Favorite")],
            "brands": [card("Coffee Giant", popularity=0.999), card("Fan Brand")]}
    tiles = mood.pick_tiles(thin, fans)
    assert [(t["name"], t.get("via")) for t in tiles] == [
        ("Wegz", None), ("19B", None), ("Anghami", None), ("Fan Favorite", "fans"), ("Fan Brand", "fans"),
        ("Local Legend", "loved"),
    ]
    # Fans whose taste Qloo did not tie to the category add nothing; household names never fill a board.
    tiles = mood.pick_tiles(thin, {**fans, "specific": False})
    assert [(t["name"], t.get("via")) for t in tiles] == [
        ("Wegz", None), ("19B", None), ("Anghami", None), ("Local Legend", "loved"), ("Kojak Studio", "loved"),
        ("Phone Network", "loved"),
    ]
    board = mood.build(run_with(thin), {"genre": "Coffee shop"}, this_year=2026)
    assert "3 marked “Loved here” are among what people here rank highest" in board["source"]
    board = mood.build(run_with(thin), {"genre": "Coffee shop"}, fans=fans, this_year=2026)
    assert "2 marked “Fans’ pick” are what people near here who love coffee shop places also love." in board["source"]


def test_an_empty_taste_makes_an_empty_board_that_still_has_a_direction():
    board = mood.build(run_with({}), {"genre": "Wine Bar"}, this_year=2026)
    assert board["tiles"] == [] and board["era"]["label"] is None and board["era"]["classic_share"] is None
    assert board["direction"]["source"] == "default" and len(board["direction"]["palette"]) == 5
    assert board["basis"].startswith("None of the names people here over-index on has a year")
    assert board["credit"] == "Images: Qloo"


# ---------- Era ----------

def test_the_era_is_the_decade_most_names_come_from_with_a_strong_neighbor():
    era = mood.read_era(FULL, 2026)
    # 1970s: 1972, 1975, 1978, 1979, 1976; 1980s: 1984, 1981; 2010s: 2019.
    assert (era.dated, era.classic, era.span, era.in_span) == (8, 7, (1970,), 5)
    assert era.payload() == {"label": "1970s", "from": 1970, "to": 1979, "classic_share": 0.88, "dated": 8, "classic": 7}

    seventies_eighties = taste(
        artists=[card("A", since=1972), card("B", since=1975)], movies=[card("C", year=1978), card("D", year=1981)],
        tv=[card("E", year=1984), card("F", year=2019), card("G", year=1979)],
    )
    era = mood.read_era(seventies_eighties, 2026)
    assert era.label == "1970s–80s" and era.payload()["to"] == 1989 and era.payload()["classic_share"] == 0.86
    board = mood.build(run_with(seventies_eighties), {"genre": "Wine Bar"}, this_year=2026)
    assert board["basis"] == (
        "6 of the 7 names people here over-index on that have a year date from the 1970s and 80s; 6 are 20 or more "
        "years old (artists by the year they started, films and shows by release)."
    )


def test_era_labels_and_spans_across_centuries():
    assert mood.decade_label((1970, 1980)) == "1970s–80s"
    assert mood.decade_label((1990, 2000)) == "1990s–2000s"
    assert mood.decade_label((2010, 2020)) == "2010s–20s"
    current = taste(movies=[card(f"M{i}", year=2016 + i) for i in range(8)])  # 2016–2023
    era = mood.read_era(current, 2026)
    assert era.label == "2010s–20s" and era.payload()["from"] == 2010 and era.payload()["to"] == 2026
    assert era.payload()["classic_share"] == 0.0


def test_too_few_or_too_spread_years_read_no_era():
    few = taste(artists=[card("A", since=1975), card("B", since=1977)], movies=[card("C", year=1979), card("D", year=1971)])
    assert not mood.read_era(few, 2026).clear
    spread = taste(movies=[card(f"M{i}", year=1955 + 10 * i) for i in range(7)])  # one name a decade
    era = mood.read_era(spread, 2026)
    assert era.dated == 7 and not era.clear and era.label is None
    # Brands and podcasts have no year; years in the future or the distant past are not read.
    odd = taste(artists=[card("Old", since=1700), card("Future", since=2090)], brands=[card("Shop", year=1980)])
    assert mood.read_era(odd, 2026).dated == 0


# ---------- Direction ----------

def test_every_era_and_style_has_a_full_direction():
    hex_code = re.compile(r"^#[0-9A-F]{6}$")
    for style in [*mood.ERA_DIRECTIONS.values(), *(entry[2] for entry in mood.DNA_STYLES), mood.CASUAL]:
        assert 4 <= len(style["palette"]) <= 5
        assert all(hex_code.match(s["hex"]) and s["name"] for s in style["palette"])
        assert len(style["materials"]) >= 3 and style["lighting"] and style["type"]
        words = " ".join([*style["materials"], style["lighting"], style["type"], *(s["name"] for s in style["palette"])])
        assert not re.search(r"\d", words)  # nothing a statement check or a render could misread as evidence
        # A direction never brings a cooking line into a unit without a hood ('charcoal' reads as a grill).
        assert not design.shows_hood_fixtures(words) and not mood.PORTRAITS.search(words)


def test_the_era_maps_to_its_row_of_the_rules_table():
    board = mood.build(run_with(FULL), {"genre": "Wine Bar"}, this_year=2026)
    direction = board["direction"]
    assert direction["name"] == "Seventies warmth" and direction["source"] == "era"
    assert [s["name"] for s in direction["palette"]][:2] == ["burnt orange", "mustard"]
    assert direction["music"] == "Records from the 1970s, as most of these names are"
    assert board["statement"] == (
        "Most of what people here over-index on, such as Jazz Elder, Harbor Lights and Pier Pressure, dates from the "
        "1970s. The room takes that era's look, made new: walnut veneer, cork and smoked glass under amber glass "
        "pendants, low and warm."
    )
    eighties = taste(movies=[card(f"M{i}", year=1980 + i) for i in range(6)])
    assert mood.build(run_with(eighties), {"genre": "Bar"}, this_year=2026)["direction"]["name"] == "Eighties gloss"
    # Decades beyond the table use its nearest row.
    forties = taste(movies=[card(f"M{i}", year=1940 + i) for i in range(6)])
    assert mood.build(run_with(forties), {"genre": "Bar"}, this_year=2026)["direction"]["name"] == "Mid-century classic"


def test_without_an_era_the_direction_follows_the_design_dna_and_says_so():
    thin = taste(artists=[card("Wegz", since=2017)], movies=[card("19B", year=2022)])
    dna = {"decor": ["Industrial chic", "Urban industrial", "Cozy"], "ambience": ["Lively"]}
    board = mood.build(run_with(thin), {"genre": "Wine Bar"}, dna, this_year=2026)
    assert board["direction"]["name"] == "Industrial" and board["direction"]["source"] == "dna"
    assert board["direction"]["cues"] == ["Industrial chic"]  # 'Urban industrial' says the same
    assert board["direction"]["music"] is None
    assert board["basis"] == (
        "Only 2 of the names people here over-index on have a year (artists by the year they started, films and shows "
        "by release): too few to read an era, so the direction follows the design DNA of the wine bar places people "
        "here love."
    )
    assert board["statement"].startswith("Too few of the names people here over-index on, such as Wegz and 19B,")
    assert "The room follows the wine bar places people here love instead: industrial chic, with" in board["statement"]
    assert mood.dna_direction({"decor": ["Casual"], "ambience": ["Lively"]})["name"] == "Plain and casual"


# ---------- The statement ----------

BOARD = mood.build(run_with(FULL), {"genre": "Wine Bar"}, this_year=2026)


@pytest.mark.parametrize("statement", [
    "Think Jazz Elder on the turntable and Harbor Lights on a quiet night: a room in burnt orange and mustard.",
    "Warm as the 1970s: Soul Sister's records, cork walls and amber glass pendants, low and warm.",
    "Picture the Seventies made new for Corner Pour in Testville. Pier Pressure sets the pace.",
    "Most of these names, 7 of 8 of them, are 20 or more years old: the room should feel like it too.",
])
def test_a_statement_with_only_the_boards_names_and_era_holds(statement):
    assert mood.check_statement(statement, BOARD, ["Corner Pour", "Test Corner", "Testville"]) == []


@pytest.mark.parametrize(("statement", "problem"), [
    ("Think Jazz Elder and Beyoncé under amber light.", "'Beyoncé' is not a name on the board"),
    ("A room for fans of Harbor Lights and Studio Ghibli.", "'Studio' is not a name on the board"),
    ("Jazz Elder has played here since 1999.", "'1999' is not a number the evidence holds"),
    ("Pure 1990s energy, with Disco Duo on repeat.", "'1990s' is not an era on the board"),
    ("Pure eighties energy, Nineties grit and Disco Duo on repeat.", "'Nineties' is not an era on the board"),
    ("Four nights a week of Soul Sister.", "'Four' is not a number the evidence holds"),
    ("Hang posters of Jazz Elder above the bar.", "it puts the names in the room (posters, portraits, photos or logos)"),
    ("Warm wood. Amber light. Soul Sister on the speakers.", "it is longer than two sentences"),
    # What a real model answered on a live survey: the names and a word, not a sentence about the room.
    ("Jazz Elder Harbor Lights Pier Pressure Soul Sister era.", "it lists names instead of saying how the room should feel"),
])
def test_a_statement_that_strays_from_the_board_is_caught(statement, problem):
    assert problem in mood.check_statement(statement, BOARD)


def test_the_boards_own_statement_passes_its_checks():
    for data in (FULL, taste(), taste(artists=[card("Wegz", since=2017)])):
        board = mood.build(run_with(data), {"genre": "Wine Bar"}, {"decor": ["Cozy"]}, this_year=2026)
        assert mood.check_statement(board["statement"], board) == [], board["statement"]


class ScriptedLLM:
    def __init__(self, *replies, enabled: bool = True) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.enabled = enabled

    async def complete_json(self, system: str, user: str):
        self.prompts.append(user)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply, "test-model"


def test_a_statement_that_holds_is_kept_without_another_call():
    llm = ScriptedLLM()
    board = asyncio.run(mood.finish(llm, BOARD, "Think Jazz Elder under amber glass pendants, low and warm"))
    assert board["statement"] == "Think Jazz Elder under amber glass pendants, low and warm."
    assert board["statement_by"] == "agent" and llm.prompts == []


def test_a_failing_statement_is_asked_for_once_more_then_replaced_by_the_boards_own():
    llm = ScriptedLLM({"statement": "Soul Sister and cork walls, the 1970s made new."})
    board = asyncio.run(mood.finish(llm, BOARD, "Beyoncé meets Jazz Elder."))
    assert board["statement"] == "Soul Sister and cork walls, the 1970s made new." and board["statement_by"] == "agent"
    assert "'Beyoncé' is not a name on the board" in llm.prompts[0] and "Jazz Elder" in llm.prompts[0]

    llm = ScriptedLLM({"statement": "Still Beyoncé."})
    board = asyncio.run(mood.finish(llm, BOARD, "Beyoncé meets Jazz Elder."))
    assert board["statement"] == BOARD["statement"] and board["statement_by"] == "rules" and len(llm.prompts) == 1

    failing = ScriptedLLM(RuntimeError("every model is resting"))
    assert asyncio.run(mood.finish(failing, BOARD, "Beyoncé meets Jazz Elder."))["statement"] == BOARD["statement"]
    off = ScriptedLLM(enabled=False)
    assert asyncio.run(mood.finish(off, BOARD, "Beyoncé meets Jazz Elder."))["statement_by"] == "rules"
    assert off.prompts == []
    assert asyncio.run(mood.finish(ScriptedLLM(), BOARD, None)) == BOARD


# ---------- Renders ----------

def test_the_render_direction_carries_the_era_palette_materials_and_light_but_no_name():
    interior, facade = mood.interior_direction(BOARD), mood.facade_direction(BOARD)
    assert interior.startswith("Design direction: the 1970s made new, in a palette of burnt orange, mustard, olive,")
    assert "walnut veneer, cork, smoked glass and terracotta tile" in interior and "amber glass pendants" in interior
    assert facade == ("The shopfront follows the same direction, the 1970s made new: burnt orange and mustard with "
                      "walnut veneer, the sign lettered in a soft, heavy serif with rounded corners.")
    for text in (interior, facade):
        assert mood.names_in(text, [t["name"] for t in BOARD["tiles"]]) == []
        assert not mood.PORTRAITS.search(text)
    # A material the palette already names as a color is not said twice.
    minimal = mood.build(run_with({}), {"genre": "Cafe"}, {"decor": ["Modern", "Stylish"]}, this_year=2026)
    assert minimal["direction"]["name"] == "Modern minimal"
    assert mood.facade_direction(minimal) == ("The shopfront follows the same direction: sage and pale oak with white "
                                              "plaster, the sign lettered in a clean grotesk.")
    assert "with white plaster, steel and glass;" in mood.interior_direction(minimal)


def test_scrub_drops_sentences_that_name_people_here_love_or_show_their_pictures():
    run = run_with(FULL)
    run.fans["tag"] = {"artists": [card("Fan Favorite")], "brands": [], "specific": True}
    names = mood.taste_names(run)
    prompt = ("A long walnut bar. Framed photographs of Jazz Elder line the wall. A shelf of records by Fan Favorite. "
              "Posters of local films by the door. Amber pendants over every table.")
    assert mood.scrub(prompt, names) == "A long walnut bar. Amber pendants over every table."
    # A name counts when it is written as one, with a capital: ordinary words are not taken for a show or a brand.
    assert mood.names_in("Power sockets by the bar", ["Power"]) == ["Power"]
    assert mood.names_in("power sockets by the bar", ["Power"]) == []
    assert mood.names_in("a nod to Harbor lights", ["Harbor Lights"]) == ["Harbor Lights"]
    assert mood.names_in("big windows, making it feel airy", ["Making It"]) == []
    assert mood.names_in("Beyonce on the speakers", ["Beyoncé"]) == ["Beyoncé"]
    # The site and the sign are not names, even when a title shares a word with them.
    assert mood.scrub('A typical Brooklyn street. The sign reads "Brooklyn Pour".', ["Brooklyn"], ["Brooklyn", "Brooklyn Pour"]) \
        == 'A typical Brooklyn street. The sign reads "Brooklyn Pour".'


def test_clip_cuts_after_a_whole_sentence():
    text = "First sentence here. Second sentence is a little longer. Third."
    assert mood.clip(text, 40) == "First sentence here."
    assert mood.clip(text, 400) == text
    assert mood.clip("one two three four five six seven", 20) == "one two three four."


# ---------- On the design sheet ----------

class Pictured(FakeQloo):
    """The fake Qloo world, with Qloo's images on its artists, films, shows and brands (the fake has none of its own)."""

    async def insights(self, params: dict) -> dict:
        data = await super().insights(params)
        found = (data.get("results") or {}).get("entities") if isinstance(data.get("results"), dict) else None
        for entity in found or []:
            if not str(entity.get("entity_id", "")).startswith("place-"):
                entity.setdefault("properties", {})["image"] = {"url": IMG.format(entity["entity_id"])}
        return data


def surveyed(**brief) -> tuple[RunState, Pictured]:
    """A run made the way the app makes one: the real pipeline over the fake Qloo world, in rules mode."""
    async def ignore(event: str, data: dict) -> None:
        pass

    async def survey() -> tuple[RunState, Pictured]:
        q = Pictured()
        site = Site(*SITE, "Test Corner, Testville", **brief)
        return await pipeline.analyze_site(q, FakeWalker(), LLM("", None, "test-model"), RunStore(), site, ignore), q

    return asyncio.run(survey())


def sheet_of(run: RunState, q: Pictured, llm=None) -> dict:
    return asyncio.run(design.design_concept(llm or LLM("", None, "test-model"), FakeImages(enabled=False), run, 0, q))


# The fake world's signature taste: Seafood fans share Local Jazz Trio and Riverside Cider Co, so they lead their kinds.
TILES = ["Local Jazz Trio", "Harbor Lights", "Pier Pressure", "Riverside Cider Co", "Block Party Band", "Dock Days",
         "Night Market", "Block News", "Local Sports Team"]


def test_a_design_sheet_carries_the_board_and_its_renders_follow_it_without_a_name():
    run, q = surveyed()
    sheet = sheet_of(run, q)
    board = sheet["mood"]
    assert [t["name"] for t in board["tiles"]] == TILES and board["credit"] == "Images: Qloo"
    # 1985, 1998, 2003, 2019, 2021, 2022: half in the 2010s and 20s, the fullest span.
    assert board["era"]["label"] == "2010s–20s" and board["era"]["dated"] == 6
    assert board["direction"]["name"] == "Warm minimal" and board["statement_by"] == "rules"
    assert board["statement"].startswith("Half of what people here over-index on, such as Local Jazz Trio, Harbor Lights "
                                         "and Pier Pressure, dates from the 2010s–20s.")
    interior, exterior = (shot["prompt"] for shot in sheet["shots"])
    assert interior.startswith("Interior of a small street-level seafood restaurant in Test Corner, Testville.")
    assert ("Design direction: the 2010s–20s made new, in a palette of clay, olive, sand, chalk and espresso, with "
            "limewash walls, travertine, microcement and curved oak") in interior
    assert "The shopfront follows the same direction, the 2010s–20s made new: clay and olive with limewash walls" in exterior
    for prompt in (interior, exterior):
        described = prompt.replace(design.INTERIOR_STYLE, "").replace(design.FACADE_STYLE, "")  # the rules say "no logos"
        assert mood.names_in(prompt, mood.taste_names(run)) == [] and not mood.PORTRAITS.search(described)
        assert "No people" in prompt and len(prompt) <= design.PROMPT_LIMIT


class ScriptedDesigner:
    """A design model that answers the design prompt with `reply` and the statement's second try from `retries`."""

    enabled = True

    def __init__(self, reply: dict, *retries: dict) -> None:
        self.reply, self.retries = reply, list(retries)
        self.mood_prompts: list[str] = []

    async def complete_json(self, system: str, user: str):
        if system.startswith("You are a concept designer"):
            assert "mood_board" in json.loads(user)
            return dict(self.reply), "test-model"
        self.mood_prompts.append(user)
        return self.retries.pop(0), "test-model"


REPLY = {
    "name": "Tide Room", "tagline": "Oysters on the corner", "concept_statement": "Because people here travel for it.",
    "interior": {"mood": "calm", "materials": ["limewash", "oak"], "lighting": "paper shades", "layout": "bar",
                 "seating": "stools"},
    "offer": ["Oysters", "Crudo"], "price_level": 2, "music": {"artists": ["Local Jazz Trio"]}, "partners": [],
    "mood_statement": "Think Beyoncé meets Harbor Lights.",
    "image_prompt": "A calm seafood room in limewash and oak. Framed posters of Harbor Lights and Pier Pressure line the "
                    "back wall. A record shelf for Local Jazz Trio. Paper lanterns over a long oak counter",
    "facade_prompt": "A slim shopfront in clay render with a Riverside Cider Co banner. The sign reads \"Tide Room\" in "
                     "small lowercase letters",
}


def test_the_models_statement_is_checked_and_its_prompts_keep_no_name_or_poster():
    run, q = surveyed()
    llm = ScriptedDesigner(REPLY, {"statement": "Soft paper light and oak, the 2010s–20s made new, with Local Jazz Trio "
                                                "on the speakers."})
    sheet = sheet_of(run, q, llm)
    board = sheet["mood"]
    assert board["statement"] == "Soft paper light and oak, the 2010s–20s made new, with Local Jazz Trio on the speakers."
    assert board["statement_by"] == "agent" and "mood_statement" not in sheet
    assert "'Beyoncé' is not a name on the board" in llm.mood_prompts[0]
    interior, exterior = (shot["prompt"] for shot in sheet["shots"])
    assert interior.startswith("A calm seafood room in limewash and oak. Paper lanterns over a long oak counter. "
                               "Design direction: the 2010s–20s made new")
    assert interior.endswith("No people, no text, no logos.")
    assert exterior.startswith('The sign reads "Tide Room" in small lowercase letters. The shopfront follows the same')
    for prompt in (interior, exterior):
        assert not {"Harbor Lights", "Pier Pressure", "Local Jazz Trio", "Riverside Cider Co"} & set(mood.names_in(prompt, TILES))
        assert "poster" not in prompt.lower()


def test_a_statement_that_breaks_the_owners_rules_gives_way_to_the_boards_own():
    run, q = surveyed(notes="budget prices")
    upscale = {**REPLY, "mood_statement": "An upscale room with Local Jazz Trio on the speakers."}
    llm = ScriptedDesigner(upscale, {"statement": "A premium room with Local Jazz Trio on the speakers."})
    board = sheet_of(run, q, llm)["mood"]
    assert board["statement_by"] == "rules" and board["statement"].startswith("Half of what people here over-index on")
    assert "it calls a budget place upscale or premium" in llm.mood_prompts[0] and len(llm.mood_prompts) == 1


def test_the_design_endpoint_serves_the_board():
    services = Services(qloo=Pictured(), walker=FakeWalker(), llm=LLM("", None, "test-model"), images=ImageGen(),
                        geocoder=StubGeocoder(), answers=AnswerCache(None))
    params = {"lat": SITE[0], "lon": SITE[1], "label": "Test Corner, Testville", "focus": "any", "minutes": 10}
    with TestClient(create_app(lambda: services)) as client:
        stream = client.get("/api/run", params=params).text
        run_id = next(json.loads(line[5:]) for line in stream.splitlines() if line.startswith("data:") and '"run_id"' in line)["run_id"]
        sheet = client.post("/api/design", json={"run_id": run_id, "index": 0}).json()
    board = sheet["mood"]
    assert board["era"]["from"] == 2010 and "from_" not in board["era"] and board["era"]["label"] == "2010s–20s"
    assert board["tiles"][3] == {"name": "Riverside Cider Co", "kind": "brand", "image": IMG.format("brand-riverside-cider-co"),
                                 "year": None, "since": None, "via": None}
    assert board["tiles"][0]["since"] == 1985 and board["tiles"][1]["year"] == 1998
    assert [s["name"] for s in board["direction"]["palette"]] == ["clay", "olive", "sand", "chalk", "espresso"]
    assert board["credit"] == "Images: Qloo" and board["basis"] and board["source"]
    assert all(not mood.names_in(shot["prompt"], TILES) for shot in sheet["shots"])
