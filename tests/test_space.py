from app import space


def test_kitchen_need_by_kind_of_business():
    assert space.kitchen_need("Seafood") == "full"
    assert space.kitchen_need("Hamburger restaurant") == "full"
    assert space.kitchen_need("Coffee shop") == "light"
    assert space.kitchen_need("Ice cream shop") == "light"
    assert space.kitchen_need("Wine Bar") == "light"
    assert space.kitchen_need("Live music venue") == "light"
    assert space.kitchen_need("Gift shop") == "none"
    assert space.kitchen_need("Yoga studio") == "none"


def test_misfit_only_when_the_unit_has_less_kitchen_than_needed():
    assert space.misfit("Seafood", "light") == "needs a full kitchen with extraction; the unit has a light-prep kitchen"
    assert space.misfit("Seafood", "full") is None
    assert space.misfit("Coffee shop", "none") == "needs a light-prep kitchen; the unit has no kitchen"
    assert space.misfit("Gift shop", "none") is None
    assert space.misfit("Seafood", None) is None  # unknown kitchen: no verdict


def test_capacity_follows_the_building_code_load_factors():
    # 100 m² restaurant: 55-65 % guest area at 1.39 m² per seated guest.
    assert space.capacity(100, "Seafood") == {"mode": "seated", "low": 39, "high": 46}
    # Standing room: 0.46 m² per guest.
    assert space.capacity(100, "Live music venue") == {"mode": "standing", "low": 139, "high": 161}
    assert space.capacity(100, "Gift shop") is None
    assert space.capacity(None, "Seafood") is None
    assert space.capacity_text({"mode": "seated", "low": 39, "high": 46}) == "about 39–46 seated guests at most"


def test_fit_and_unit_text_need_some_unit_details():
    assert space.fit("Seafood", None, None) is None
    assert space.fit("Seafood", 80, None)["fits"] is True
    assert space.fit("Seafood", None, "none")["reason"] == "needs a full kitchen with extraction; the unit has no kitchen"
    assert space.unit_text(None, None, None) is None
    assert space.unit_text(None, None, True) == {"size": "unknown", "kitchen": "unknown", "outdoor_space": "yes"}
    assert space.size_text(92.903) == "93 m² (1,000 ft²)"
