"""The themed wild card: a kind of place people here love, hosting what they watch, hear and follow (Qloo's taste across
shows, films, podcasts, artists and brands). Only the area's distinctive titles count; a theme needs several of them, is
never about who people are, and is skipped where a place inside the area is already known for it. It keeps the owner's
rules, comes before the two-loves wild card, and its design sheet and launch kit work like any concept's."""
from __future__ import annotations

import asyncio
import copy
import json

import pytest

from app import schemas, scoring
from app.qloo import QlooError
from app.survey import concepts, experience, launch, themes
from app.survey.models import RunState, Site
from tests.account_fakes import configure, run_survey
from tests.account_fakes import make_client as account_client
from tests.fakes import AUDIENCE_AGES, FakeQloo, ThemedQloo, place, slug
from tests.test_e2e import RUN_PARAMS, first, make_client, scripted_llm, sse_events, tool_call
from tests.test_kits_api import make_kit, wait_for
from tests.test_owner_rules import SITE, burger_joint, cocktail_bar, coffee_shop, world


def card(name: str, *genres: str, image: str | None = None) -> dict:
    """A distinctive taste card as engine.local_taste keeps it."""
    return {"id": f"id-{slug(name)}", "name": name, "image": image, "popularity": 0.9, "genres": list(genres)}


def taste(**domains: list[dict]) -> dict:
    return {f"distinctive_{domain}": cards for domain, cards in domains.items()}


REALITY = taste(
    tv=[card("Shore Thing", "Reality tv", "Reality"), card("Flip This Loft", "Reality tv", "Reality")],
    podcasts=[card("Rose Recap", "TV & Film", "Society & Culture")],
)
RAPPERS = [card(f"MC {name}", "Hip Hop", "Rap", "Trap") for name in ("Ace", "Blue", "Cove", "Dune")]
DJS = [card(f"DJ {name}", "Electronic", "House", "Techno") for name in ("Ash", "Birch", "Cedar", "Dew")]


def themed_world(notes: str = "", taste_: dict = REALITY, **options) -> RunState:
    run = world(notes, **options)
    run.taste = copy.deepcopy(taste_)
    return run


def wildcard_of(built: list[dict]) -> dict | None:
    return next((c for c in built if c.get("wildcard")), None)


def found_keys(taste_: dict, notes: str = "") -> list[str]:
    return [theme.key for theme, _ in themes.found(taste_, world(notes).constraints)]


# ---------- Genres and detection ----------

def test_cards_keep_each_genre_once_in_the_order_of_their_tag_types():
    entity = {"tags": [
        {"type": "urn:tag:genre:music", "name": "Rhythm & Blues"}, {"type": "urn:tag:genre:qloo", "name": "R & B"},
        {"type": "urn:tag:genre:qloo", "name": "R&B"}, {"type": "urn:tag:genre:qloo", "name": "Hip Hop"},
        {"type": "urn:tag:genre:music", "name": "Hip - Hop"}, {"type": "urn:tag:theme:qloo", "name": "Love"},
        {"type": "urn:tag:genre:music", "name": "مهرجانات"},
    ]}
    types = ("urn:tag:genre:qloo", "urn:tag:genre:music")
    assert scoring.tag_names(entity, types) == ["R & B", "Hip Hop", "Rhythm & Blues", "مهرجانات"]
    assert scoring.tag_names(entity, types, limit=2) == ["R & B", "Hip Hop"]


def test_a_theme_needs_three_titles_from_two_domains_or_four_from_one():
    assert found_keys(REALITY) == ["reality_tv"]
    assert found_keys(taste(tv=REALITY["distinctive_tv"])) == []  # two shows are one fan base, not a theme
    assert found_keys(taste(artists=RAPPERS[:3])) == []
    assert found_keys(taste(artists=RAPPERS)) == ["hip_hop"]
    # Reality TV needs a reality show: podcasts about TV and film alone may be about films.
    film_talk = [card(f"Film Talk {i}", "TV & Film", "Film Reviews") for i in range(4)]
    assert found_keys(taste(podcasts=film_talk)) == []


def test_a_title_counts_for_the_theme_its_genres_name_most():
    pop_star = card("Shiny", "Pop", "Dance Pop", "Electropop", "Hip - Hop")
    assert [theme.key for theme in themes.counts_for(pop_star, "artists")] == ["pop_karaoke"]
    assert found_keys(taste(artists=[*RAPPERS[:3], pop_star])) == []
    # Genres on half the titles anywhere name no theme: a run of dramas and comedies is no theme.
    assert themes.counts_for(card("Drama Hour", "Drama", "Comedy", "Crime"), "tv") == []


def test_only_the_distinctive_taste_counts():
    popular = {"artists": RAPPERS, "brands": [card(f"Club {i}", "Professional Sports", "Soccer") for i in range(4)]}
    assert found_keys(popular) == []
    assert found_keys({**popular, **taste(artists=RAPPERS)}) == ["hip_hop"]


def test_the_strongest_theme_wins_then_the_one_on_more_domains_then_the_first_listed():
    comedy = [card(f"Laugh Pod {i}", "Comedy", "Society & Culture") for i in range(4)]
    assert found_keys({**REALITY, **taste(podcasts=[*REALITY["distinctive_podcasts"], *comedy])}) == ["comedy", "reality_tv"]
    sports = taste(brands=[card("City FC", "Professional Sports", "Soccer"), card("Metro Ballers", "Basketball", "NBA")],
                   podcasts=[card("Full Time", "Sports", "Football")])
    both = {**REALITY, **sports, "distinctive_podcasts": REALITY["distinctive_podcasts"] + sports["distinctive_podcasts"]}
    assert found_keys(both) == ["reality_tv", "sports"]  # three titles from two domains each: the one listed first leads
    four_shows = taste(tv=[card(f"Show {i}", "Reality tv") for i in range(4)])
    four_on_two = taste(brands=[card(f"Club {i}", "Professional Sports", "Soccer") for i in range(3)],
                        podcasts=[card("Full Time", "Sports")])
    assert found_keys({**four_shows, **four_on_two}) == ["sports", "reality_tv"]  # as many titles, on more domains


def test_faith_politics_and_identity_are_never_themes_and_their_titles_never_count():
    sermons = [card(f"Sunday Word {i}", "Religion & Spirituality", "Christianity") for i in range(5)]
    assert found_keys(taste(podcasts=sermons)) == []
    tagged = taste(tv=[card("Shore Thing", "Reality tv", "Lgbtq"), card("Flip This Loft", "Reality tv")],
                   podcasts=[card("Rose Recap", "TV & Film"), card("Ballot Talk", "TV & Film", "Politics")])
    assert found_keys(tagged) == []  # one show and one podcast are left: no theme
    assert found_keys(taste(artists=[*RAPPERS[:3], card("Choir Kid", "Rap", "Gospel")])) == []


def test_a_title_whose_name_breaks_the_owners_rules_never_counts():
    happy_hour = taste(tv=REALITY["distinctive_tv"], podcasts=[card("Rosé Happy Hour", "TV & Film")])
    assert found_keys(happy_hour) == ["reality_tv"]
    assert found_keys(happy_hour, "no alcohol") == []


# ---------- The concept ----------

def test_the_themed_wildcard_comes_after_the_ranked_concepts_instead_of_the_two_loves_one():
    run = themed_world()
    built = concepts.rule_concepts(run)
    wildcard = built[-1]
    assert [c.get("wildcard", False) for c in built] == [False] * (len(built) - 1) + [True]
    assert wildcard["genre"] == "Cocktail bar" and wildcard["gap_score"] is None
    word = wildcard["name"].removesuffix(" Bar")
    assert word in themes.THEMES[0].name_words and wildcard["name"] not in [c["name"] for c in built[:-1]]
    assert wildcard["combines"] == [
        {"item": "cocktail bars", "genre": "Cocktail bar",
         "source": "People here travel a median 2.5 km to the cocktail bars they love most, such as Velvet Room 0 and "
                   "Velvet Room 1 (Qloo)."},
        {"item": "reality TV", "genre": "",
         "source": "People here over-index on Shore Thing, Flip This Loft and Rose Recap compared with same-size areas "
                   "around (Qloo)."},
    ]
    assert wildcard["theme"] == {
        "key": "reality_tv",
        "label": "reality TV",
        "program": ["Watch parties for Shore Thing and Flip This Loft", "Recap nights on Rose Recap"],
        "built_on": [
            {"domain": "tv", "id": "id-shore-thing", "name": "Shore Thing"},
            {"domain": "tv", "id": "id-flip-this-loft", "name": "Flip This Loft"},
            {"domain": "podcasts", "id": "id-rose-recap", "name": "Rose Recap"},
        ],
        "draws": None,
        "basis": "What people within 1.5 km over-index on compared with same-size areas a few kilometres around (Qloo).",
    }
    assert wildcard["one_liner"] == ("A cocktail bar with reality-TV watch parties: people here over-index on reality TV, "
                                     "and nothing inside the 10-minute walk is known for it.")
    assert wildcard["for_whom"] == "Neighbors within a 10-minute walk who love reality TV"
    assert wildcard["why_here"] == [
        "People here travel a median 2.5 km to the cocktail bars they love most, such as Velvet Room 0 and Velvet Room 1.",
        "People here over-index on Shore Thing, Flip This Loft and Rose Recap compared with same-size areas around.",
        "No place inside the 10-minute walk is known for reality TV.",
    ]
    assert wildcard["beat_competitors"] == ("No place inside the walk is known for reality TV; the nearest competition is "
                                            "the 4 cocktail bars inside the walk.")
    assert wildcard["signature"] == [
        "Reality-TV watch parties", "Banana espresso martini", "Deviled eggs", "Crispy potatoes",
    ]
    assert wildcard["inspired_by"] == ["Velvet Room 0", "Velvet Room 1", "Velvet Room 2"]
    assert wildcard["caution"] == wildcard["risk"] == concepts.THEMED_CAUTION and wildcard["owner_rules"] == []
    # It is never ranked, and the payload shape is the documented one.
    assert concepts.caution(run, [{**c, "gap_score": 12} for c in built[:-1]] + [wildcard]).startswith("No strong gap")
    validated = schemas.Concept.model_validate(wildcard)
    assert validated.theme.built_on[2].domain == "podcasts" and validated.combines[1].genre == ""


def test_surveys_saved_before_genres_existed_keep_the_two_loves_wildcard():
    old = {key: [{k: v for k, v in c.items() if k != "genres"} for c in cards] for key, cards in REALITY.items()}
    wildcard = wildcard_of(concepts.rule_concepts(themed_world(taste_=old)))
    assert "theme" not in wildcard and [side["genre"] for side in wildcard["combines"]] == ["Cocktail bar", "Coffee shop"]
    assert wildcard["caution"] == concepts.WILDCARD_CAUTION


def test_a_failing_theme_never_costs_the_concepts(monkeypatch: pytest.MonkeyPatch):
    def broken(*args, **kwargs):
        raise KeyError("genres")

    monkeypatch.setattr(themes, "found", broken)
    built = concepts.rule_concepts(themed_world())
    assert [c for c in built if not c.get("wildcard")] and "theme" not in wildcard_of(built)


def test_a_theme_a_place_inside_already_offers_is_skipped_for_the_next_one():
    run = themed_world(taste_={**REALITY, **taste(artists=[card(f"Star {i}", "Pop", "Dance Pop") for i in range(4)])})
    assert themes.known_inside(run, themes.THEMES[5]) is None
    assert wildcard_of(concepts.rule_concepts(run))["theme"]["key"] == "pop_karaoke"  # four titles beat three
    karaoke = place("Mic Night", "Karaoke bar", SITE[0] + 0.001, SITE[1], 60)
    run.block.append(karaoke)
    assert themes.known_inside(run, themes.THEMES[5]) == "Mic Night"
    assert wildcard_of(concepts.rule_concepts(run))["theme"]["key"] == "reality_tv"
    # A sports pub's watch parties are sports: nothing inside is known for reality TV.
    pub = place("The Corner Pub", "Sports bar", SITE[0] + 0.002, SITE[1], 61)
    pub["tags"].append({"type": "urn:tag:activity_type:qloo", "name": "Watch parties"})
    run.block.append(pub)
    assert themes.known_inside(run, themes.THEMES[0]) is None
    # A place known for every theme found leaves the two-loves wildcard.
    run.block.append(place("Reality TV Lounge", "Lounge", SITE[0] + 0.003, SITE[1], 62))
    assert "theme" not in wildcard_of(concepts.rule_concepts(run))


def test_the_owners_rules_choose_the_place_and_the_theme():
    # No alcohol: never a bar; the coffee shop people here travel to hosts the watch parties.
    run = themed_world("no alcohol")
    wildcard = wildcard_of(concepts.rule_concepts(run))
    assert wildcard["genre"] == "Coffee shop" and wildcard["name"].endswith(" Coffee")
    assert all(run.constraints.allows_item(item) for item in wildcard["signature"])
    assert "No alcohol on the menu." in wildcard["owner_rules"]
    # Family friendly: DJ nights are nightlife, so the next theme is used, in a place for families.
    run = themed_world("family friendly", taste_={**REALITY, **taste(artists=DJS)})
    assert found_keys(run.taste)[0] == "electronic"
    wildcard = wildcard_of(concepts.rule_concepts(run))
    assert wildcard["theme"]["key"] == "reality_tv" and wildcard["genre"] != "Cocktail bar"
    assert "Family friendly: no bar and no nightlife." in wildcard["owner_rules"]
    # The unit: its size is said, and a cook-along needs a kitchen it does not have.
    assert wildcard_of(concepts.rule_concepts(themed_world(size_m2=45)))["owner_rules"][0] == (
        "Fits 45 m² (484 ft²): a bar counter and about 20–24 seats at most.")
    food_tv = taste(tv=[card("Bake Off Street", "Reality", "Baking competition"), card("Chef Wars", "Culinary competition")],
                    podcasts=[card("Kitchen Table", "Food")])
    assert found_keys(food_tv) == ["food_tv"]
    run = themed_world(size_m2=45, kitchen="none", taste_=food_tv)
    assert run.constraints.item_problem(themes.THEMES[13].activity) == "needs cooking, and the unit has no kitchen"
    assert "theme" not in (wildcard_of(concepts.rule_concepts(run)) or {})


def test_an_age_focus_is_said_wherever_people_are():
    run = themed_world()
    run.site.ages = "25_34"
    wildcard = wildcard_of(concepts.rule_concepts(run))
    assert wildcard["for_whom"] == "Neighbors aged 25–34 within a 10-minute walk who love reality TV"
    assert wildcard["combines"][1]["source"].startswith("People here aged 25–34 over-index on Shore Thing")
    assert wildcard["one_liner"].endswith("people here aged 25–34 over-index on reality TV, and nothing inside the "
                                          "10-minute walk is known for it.")
    assert wildcard["theme"]["basis"].startswith("What people aged 25–34 within 1.5 km over-index on")


def test_the_themed_wildcard_names_itself_from_the_theme_whatever_the_model_proposed():
    run = themed_world()
    ranked = [c for c in concepts.rule_concepts(run) if not c.get("wildcard")]
    # The model named a wildcard of a cocktail bar and a coffee shop: never the theme, which it was not shown.
    proposal = {"name": "Night Shift", "one_liner": "Reality TV nights at the bar, with espresso martinis"}
    with_proposal = concepts.with_wildcard(run, ranked, proposal)[-1]
    assert with_proposal == concepts.themed_wildcard(run, ranked)
    assert with_proposal["name"] != "Night Shift"
    assert any(with_proposal["name"].startswith(word) for word in themes.THEMES[0].name_words)
    assert with_proposal["one_liner"].startswith("A cocktail bar with reality-TV watch parties")


# ---------- Who it draws ----------

def test_draws_reads_who_the_fans_of_its_titles_lean_toward():
    theme = {"label": "reality TV", "built_on": [{"id": "a"}, {"id": "b"}, {"id": "c"}]}
    qloo = FakeQloo()
    assert asyncio.run(themes.draws(qloo, theme)) == {"ages": ["30–34", "35–44"], "gender": "female",
                                                      "basis": themes.DRAWS_BASIS}
    assert qloo.requests == [{"filter.type": "urn:demographics", "signal.interests.entities": "a,b,c"}]


class FlatAudience(FakeQloo):
    """Every title's fans engage like everyone does."""

    async def insights(self, params: dict) -> dict:
        ids = params["signal.interests.entities"].split(",")
        flat = {"age": dict.fromkeys(AUDIENCE_AGES, 0.0), "gender": {"female": 0.05, "male": -0.05}}
        return {"results": {"demographics": [{"entity_id": i, "query": flat} for i in ids]}}


def test_draws_is_none_when_nothing_leans_too_few_titles_answer_or_qloo_fails():
    theme = {"label": "reality TV", "built_on": [{"id": "a"}, {"id": "b"}, {"id": "c"}]}
    assert asyncio.run(themes.draws(FlatAudience(), theme)) is None
    few = FakeQloo()
    assert asyncio.run(themes.draws(few, {**theme, "built_on": theme["built_on"][:2]})) is None and few.requests == []
    assert asyncio.run(themes.draws(FakeQloo(fail=True), theme)) is None
    assert asyncio.run(themes.draws(Garbled(), theme)) is None


class Garbled(FakeQloo):
    """Qloo answering the audience read with something the client cannot read."""

    async def insights(self, params: dict) -> dict:
        raise ValueError("Expecting value: line 1 column 1 (char 0)")


class NoAudience(ThemedQloo):
    async def insights(self, params: dict) -> dict:
        if params["filter.type"] == "urn:demographics":
            raise QlooError("Qloo returned HTTP 500")
        return await super().insights(params)


# ---------- Over the HTTP app ----------

def test_a_survey_reads_who_the_themed_wildcard_draws_in_one_qloo_call():
    qloo = ThemedQloo()
    with make_client(qloo=qloo) as client:
        events = sse_events(client.get("/api/run", params=RUN_PARAMS).text)
        taste_event, payload = first(events, "taste"), first(events, "concepts")
        assert taste_event["distinctive_tv"][0]["genres"] == ["Reality tv"] and "genres" not in taste_event["artists"][0]
        wildcard = payload["concepts"][-1]
        assert [c.get("wildcard", False) for c in payload["concepts"]] == [False, False, False, True]
        assert wildcard["genre"] == "Wine Bar" and wildcard["theme"]["key"] == "reality_tv"
        assert wildcard["theme"]["program"] == [
            "Watch parties for Pier Pressure and Night Market", "Recap nights on Block Radio",
        ]
        assert wildcard["theme"]["built_on"][0] == {"domain": "tv", "id": "tv_show-pier-pressure", "name": "Pier Pressure",
                                                    "image": "https://img.test/pier-pressure.jpg"}
        assert wildcard["theme"]["draws"] == {"ages": ["30–34", "35–44"], "gender": "female", "basis": themes.DRAWS_BASIS}
        audience = [r for r in qloo.requests if r.get("filter.type") == "urn:demographics"]
        assert audience == [{"filter.type": "urn:demographics",
                             "signal.interests.entities": "tv_show-pier-pressure,tv_show-night-market,podcast-block-radio"}]
        assert first(events, "done")["qloo_calls"] == qloo.calls  # counted like every other Qloo read
        schemas.Concept.model_validate(wildcard)

    with make_client(qloo=NoAudience()) as client:
        events = sse_events(client.get("/api/run", params=RUN_PARAMS).text)
        assert "error" not in [event for event, _ in events]
        assert first(events, "concepts")["concepts"][-1]["theme"]["draws"] is None


def test_the_agent_path_gets_the_themed_wildcard_with_no_other_model_call():
    requests: list[dict] = []
    submit = [tool_call("c1", "submit_concepts", {
        "concepts": [{"name": "Tide & Table", "genre": "Seafood", "one_liner": "Raw bar", "signature": ["Oysters"]}],
        "wildcard": {"name": "Shuck & Pour", "one_liner": "Oysters at the counter, a wine list to match",
                     "signature": ["Oysters", "Orange wine"]},
    })]
    with make_client(llm=scripted_llm([submit], requests), qloo=ThemedQloo()) as client:
        payload = first(sse_events(client.get("/api/run", params=RUN_PARAMS).text), "concepts")
        assert payload["mode"] == "agent" and len([body for body in requests if body.get("tools")]) == 1
        wildcard = payload["concepts"][-1]
        # The model named a wildcard of a seafood place and a wine bar; the theme names its own, in the wine bar.
        assert wildcard["name"] == "Confessional Wine Room" and wildcard["theme"]["key"] == "reality_tv"
        assert wildcard["one_liner"].startswith("A wine bar with reality-TV watch parties")
        assert wildcard["signature"][0] == "Reality-TV watch parties" and "Oysters" not in wildcard["signature"]
        assert sum(1 for c in payload["concepts"] if c.get("wildcard")) == 1


@pytest.fixture
def account_settings(monkeypatch):
    return configure(monkeypatch)


def test_a_themed_wildcard_has_a_design_sheet_and_a_launch_kit(account_settings):
    with account_client(qloo=ThemedQloo()) as client:
        run_id = run_survey(client)
        events = client.get(f"/api/runs/{run_id}").json()["events"]
        built = next(data for event, data, _ in events if event == "concepts")["concepts"]
        index = next(i for i, c in enumerate(built) if c.get("theme"))
        sheet = client.post("/api/design", json={"run_id": run_id, "index": index}).json()
        assert sheet["name"] == built[index]["name"] and sheet["offer"][0] == "Reality-TV watch parties"
        assert [item["name"] for item in sheet["experience"]["screen"]][:2] == ["Pier Pressure", "Night Market"]
        assert [item["name"] for item in sheet["experience"]["talks"]] == ["Block Radio"]
        assert sheet["launch"]["audience"]["screen"][:2] == ["Pier Pressure", "Night Market"]

        page = wait_for(client, make_kit(client, run_id, index)["token"])
        assert page["status"] == "ready" and page["name"] == built[index]["name"]
        kit = page["kit"]
        assert kit["notes"][0].startswith("Untested") and kit["dossier"]["sections"]
        # The shows are for the program and for targeting: no ad names them.
        assert "Pier Pressure" not in json.dumps(kit["copy"], ensure_ascii=False)


# ---------- Where the theme's titles lead ----------

def test_the_experience_plan_and_the_audiences_lead_with_the_themes_titles():
    run = RunState(id="r", site=Site(0, 0, "Test"))
    run.taste = {
        "distinctive_artists": [card("Indie Band")],
        "distinctive_movies": [card("Harbor Film")],
        "distinctive_tv": [card("Pier Show"), card("Shore Thing")],
        "distinctive_podcasts": [card("Block Radio"), card("Rose Recap")],
    }
    theme = {"built_on": [{"domain": "tv", "id": "id-shore-thing", "name": "Shore Thing"},
                          {"domain": "podcasts", "id": "id-rose-recap", "name": "Rose Recap"}]}
    plain = experience.plan(run, "Coffee shop", this_year=2026)
    assert "screen" not in plain and [t["name"] for t in plain["talks"]] == ["Block Radio", "Rose Recap"]
    themed = experience.plan(run, "Coffee shop", this_year=2026, theme=theme)
    assert [s["name"] for s in themed["screen"]] == ["Shore Thing", "Harbor Film", "Pier Show"]  # watch parties need one
    assert [t["name"] for t in themed["talks"]] == ["Rose Recap", "Block Radio"]
    audience = launch.reach(run, None, set(), {"Shore Thing", "Rose Recap"})
    assert audience["screen"][0] == "Shore Thing" and audience["podcasts"] == ["Rose Recap", "Block Radio"]


def test_the_theme_catalog_is_plain_and_complete():
    keys = [theme.key for theme in themes.THEMES]
    assert len(keys) == len(set(keys)) and 14 <= len(keys) <= 18
    for theme in themes.THEMES:
        assert theme.kinds and set(theme.kinds) <= {"cafe", "food", "bar", "venue", "retail", "wellness"}
        assert set(theme.match) <= {"tv", "movies", "podcasts", "artists", "brands"} and len(theme.name_words) >= 3
        assert all(domain in theme.match and "{}" in line for domain, line in theme.program)
        assert not themes.SENSITIVE.search(f"{theme.label} {theme.activity}")
        assert not concepts.FILLER.search(" ".join(line for _, line in theme.program))
    assert {theme.key for theme in themes.THEMES if theme.nightlife} == {"electronic"}
    rows = [cocktail_bar(), coffee_shop(), burger_joint()]
    assert [concepts.place_kind(row["genre"]) for row in rows] == ["bar", "cafe", "food"]


# A Qloo genre that names each theme alone, and the domain it is found in.
SAMPLE_GENRES = {
    "reality_tv": ("tv", "Reality tv"), "sports": ("brands", "Professional Sports"),
    "true_crime": ("podcasts", "True Crime"), "comedy": ("podcasts", "Comedy Interviews"), "hip_hop": ("artists", "Rap"),
    "pop_karaoke": ("artists", "Pop"), "country": ("artists", "Country"), "latin": ("artists", "Reggaeton"),
    "soul_rnb": ("artists", "Neo Soul"), "indie_vinyl": ("artists", "Indie Rock"), "electronic": ("artists", "Techno"),
    "kpop_anime": ("artists", "Idol"), "scifi_fantasy": ("movies", "Science fiction"),
    "food_tv": ("tv", "Culinary competition"), "fitness": ("brands", "Health & Wellness"),
    "outdoors": ("brands", "Outdoor Equipment"), "family": ("movies", "Family"),
}


@pytest.mark.parametrize("theme", themes.THEMES, ids=lambda theme: theme.key)
def test_every_theme_makes_a_concept_that_keeps_the_owners_rules(theme):
    domain, genre = SAMPLE_GENRES[theme.key]
    found = taste(**{domain: [card(f"{genre} Title {i}", genre) for i in range(4)]})
    assert found_keys(found) == [theme.key]
    for notes in ("", "no alcohol", "family friendly", "halal, family friendly, budget prices", "vegetarian, no hood"):
        run = themed_world(notes, size_m2=60, taste_=found)
        wildcard = wildcard_of(concepts.rule_concepts(run))
        if not notes:
            assert wildcard["theme"]["key"] == theme.key
        if not wildcard or "theme" not in wildcard:
            continue  # the rules ruled the theme out (nightlife for a family), or no loved place they allow suits it
        schemas.Concept.model_validate(wildcard)
        assert concepts.rule_problems(run, concepts.gap_for(run, wildcard["genre"]), wildcard) == []
        assert not any(run.constraints.item_problem(line) for line in wildcard["theme"]["program"])
        assert concepts.place_kind(wildcard["genre"]) in theme.kinds and len(wildcard["theme"]["built_on"]) == 4
        assert not (theme.nightlife and run.constraints.family)
