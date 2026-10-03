"""Attribute extraction: colour shades, brand aliases, model numbers, typed features, Roman-Urdu."""

from types import SimpleNamespace

from app.ai.understanding import (
    color_compatibility,
    extract_brand,
    extract_color_shades,
    extract_colors,
    extract_models,
    extract_typed_features,
    normalize_brand,
    normalize_category,
    understand,
)


def rep(**kw):
    base = dict(category="Bag", name="Bag", description="", color=None, brand=None, model=None,
                distinctive_features=None)
    base.update(kw)
    return SimpleNamespace(**base)


def compat(a: str, b: str):
    return color_compatibility(extract_colors(a), extract_colors(b))


def test_colour_shades_and_compatibility():
    assert extract_color_shades("dark blue jacket") == {("blue", "dark")}
    assert compat("navy", "dark blue") == ("same", 1.0)
    assert compat("maroon", "red") == ("same", 1.0)  # same family, different shade
    assert compat("black", "grey") == ("near", 0.5)  # visually close families
    assert compat("black", "red") == ("conflict", 0.0)
    assert compat("", "red") is None  # no colour on one side: no evidence either way


def test_roman_urdu_colours():
    assert extract_colors("kala thaila") == {"black"}
    assert extract_colors("neela bag") == {"blue"}
    assert extract_colors("laal aur safed") == {"red", "white"}


def test_brand_aliases_and_canonical_forms():
    assert extract_brand("my Jan Sport bag") == "jansport"
    assert extract_brand("hewlett packard laptop") == "hp"
    assert extract_brand("iPhone 13") == "apple"
    assert normalize_brand("JanSport") == "jansport"
    assert normalize_brand("  Hewlett Packard ") == "hp"
    assert extract_brand("a plain bag") is None


def test_model_numbers():
    assert extract_models("my iPhone 13 pro") == ["iphone13"]
    assert extract_models("Samsung Galaxy A52 with a crack") == ["galaxya52"]
    assert extract_models("model SM-A525F") == ["sma525f"]
    assert extract_models("found at 5pm near gate") == []  # times are not model numbers


def test_typed_features_and_their_colours():
    feats = extract_typed_features("red keychain on zipper and a scratch on the back")
    by_kind = {f.kind: f for f in feats}
    assert by_kind["accessory"].phrase == "red keychain on zipper"
    assert by_kind["accessory"].colors == {"red"}
    assert "scratch" in by_kind["damage"].phrase


def test_roman_urdu_category_synonyms():
    assert normalize_category("chabi")[0] == "keys"
    assert normalize_category("batwa brown")[0] == "wallet"
    assert normalize_category("shanakhti card")[0] == "id card"


def test_understanding_records_shades_models_and_rule_source():
    from app.models.enums import AttributeSource

    u = understand(rep(category="Phone", name="Galaxy A52", description="blue phone with a cracked corner",
                       color="Navy blue", brand=None))
    assert ("blue", "dark") in u.shades
    assert u.brand == "samsung"  # from the 'galaxy' alias
    assert "galaxya52" in u.models
    by = {(a.name, a.value): a.source for a in u.attributes}
    assert by[("brand", "samsung")] == AttributeSource.RULE
    assert by[("model", "galaxya52")] == AttributeSource.RULE
