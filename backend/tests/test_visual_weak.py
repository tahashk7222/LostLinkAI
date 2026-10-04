"""Visual-only Weak leads (scoring v3).

A compatible pair (same category, same place, compatible time) whose photos match at or above VISUAL_ONLY_WEAK is
stored as a WEAK lead. It never notifies, never qualifies as Strong or Possible, and never creates identity.
Contradictions still block it. Thresholds and identity rules are unchanged.
"""

from PIL import Image, ImageDraw
from types import SimpleNamespace

from app.ai.matching import VISUAL_ONLY_WEAK
from app.ai.providers import get_image_embedder
from tests.test_ai_units import report
from tests.test_scoring_v3 import _same_spot, _score, _with_image


def test_visual_only_pair_with_no_identity_is_a_stored_weak_lead_and_never_notifies():
    lost = _with_image(report(category="Charger", name="Charger", description="charger", **_same_spot()), (30, 30, 30))
    found = _with_image(report(category="Charger", name="Charger", description="charger", **_same_spot()), (30, 30, 30))
    res = _score(lost, found)
    assert res.signals["image"] >= VISUAL_ONLY_WEAK
    assert res.identity_groups == [] and res.corroborating == []  # no colour, brand, feature or identity at all
    assert res.lead == "WEAK"  # stored and shown
    assert res.notify_eligible is False  # never notifies


def test_visual_match_with_different_category_is_not_a_lead():
    lost = _with_image(report(category="Charger", name="Charger", description="charger", **_same_spot()), (30, 30, 30))
    found = _with_image(report(category="Laptop", name="Laptop", description="laptop", **_same_spot()), (30, 30, 30))
    res = _score(lost, found)
    assert res.signals["image"] >= VISUAL_ONLY_WEAK
    assert res.lead is None  # category contradiction caps the pair


def test_visual_match_with_a_colour_conflict_is_not_a_lead():
    lost = _with_image(report(category="Charger", name="Charger", description="charger", color="black",
                              **_same_spot()), (30, 30, 30))
    found = _with_image(report(category="Charger", name="Charger", description="charger", color="white",
                               **_same_spot()), (30, 30, 30))
    res = _score(lost, found)
    assert res.signals["image"] >= VISUAL_ONLY_WEAK
    assert res.lead is None  # a colour contradiction is never overridden by photos
    assert res.notify_eligible is False


def _silhouette_image(kind):
    pic = Image.new("RGB", (240, 240), (235, 235, 235))
    draw = ImageDraw.Draw(pic)
    if kind == "rectangle":
        draw.rectangle((70, 60, 170, 190), fill=(30, 30, 30))
    else:  # a different silhouette: two discs, the shape a rectangle cannot match
        draw.ellipse((40, 40, 120, 120), fill=(30, 30, 30))
        draw.ellipse((120, 120, 200, 200), fill=(30, 30, 30))
    return pic


def test_visually_different_objects_in_the_same_category_are_not_a_lead():
    lost = _with_image(report(category="Charger", name="Charger", description="charger", **_same_spot()), (30, 30, 30))
    found = report(category="Charger", name="Charger", description="charger", **_same_spot())
    found.images = [SimpleNamespace(embedding=get_image_embedder().embed(_silhouette_image("discs")))]
    res = _score(lost, found)
    assert res.signals["image"] < VISUAL_ONLY_WEAK
    assert res.lead is None


def test_missing_colour_on_both_sides_is_unknown_not_contradictory():
    lost = _with_image(report(category="Charger", name="Charger", description="charger", **_same_spot()), (30, 30, 30))
    found = _with_image(report(category="Charger", name="Charger", description="charger", **_same_spot()), (30, 30, 30))
    res = _score(lost, found)
    assert "color" not in res.signals  # absent, not a contradiction
    assert not any(e["direction"] == "contradicts" for e in res.evidence)
    assert res.lead == "WEAK"


def test_visual_only_lead_is_never_strong_or_possible_even_with_identical_photos():
    lost = _with_image(report(category="Charger", name="Charger", description="charger", **_same_spot()), (30, 30, 30))
    found = _with_image(report(category="Charger", name="Charger", description="charger", **_same_spot()), (30, 30, 30))
    res = _score(lost, found)
    assert res.lead not in ("STRONG", "POSSIBLE")
    assert res.identity_groups == []
