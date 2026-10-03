"""Structured match evidence: direction, strength labels, and consistency with display text."""

from datetime import datetime, timezone

from app.ai.config import get_matching_config
from app.ai.matching import score_pair
from app.ai.understanding import understand
from tests.conftest import register
from tests.helpers import FOUND_BACKPACK, LOST_BACKPACK
from tests.test_ai_units import report

STRENGTHS = {"STRONG", "MODERATE", "WEAK"}
DIRECTIONS = {"supports", "contradicts"}


def _score(lost, found):
    cfg = get_matching_config()
    return score_pair(lost, found, understand(lost), understand(found), cfg)


def test_evidence_items_are_structured_and_labelled():
    lost = report(color="black", brand="jansport", description="black jansport backpack lost at library",
                  distinctive_features="red keychain", latitude=33.6425, longitude=72.9930)
    good = report(category="bag", color="black", brand="jansport", description="found black jansport backpack",
                  distinctive_features="red keychain on zipper", latitude=33.6431, longitude=72.9941,
                  date_time=datetime(2026, 10, 1, 15, 30, tzinfo=timezone.utc))
    res = _score(lost, good)

    assert res.evidence, "a matching pair should produce evidence"
    for e in res.evidence:
        assert set(e) == {"signal", "text", "direction", "strength", "value"}
        assert e["strength"] in STRENGTHS
        assert e["direction"] in DIRECTIONS
    brand = next(e for e in res.evidence if e["signal"] == "brand")
    assert brand["direction"] == "supports" and brand["strength"] == "STRONG"


def test_display_text_is_derived_from_evidence():
    lost = report(color="black", brand="jansport", description="black jansport backpack")
    other = report(category="phone", name="phone", color="silver", brand="samsung", description="silver samsung phone",
                   date_time=datetime(2026, 10, 5, tzinfo=timezone.utc))
    res = _score(lost, other)

    assert res.reasons == [e["text"] for e in res.evidence if e["direction"] == "supports"]
    assert res.concerns == [e["text"] for e in res.evidence if e["direction"] == "contradicts"]
    assert res.explanation == res.reasons + [f"Note: {c}" for c in res.concerns]
    category = next(e for e in res.evidence if e["signal"] == "category")
    assert category == {"signal": "category", "text": "Item categories differ", "direction": "contradicts",
                        "strength": "STRONG", "value": None}


def test_brand_mismatch_is_a_strong_contradiction():
    lost = report(color="black", brand="jansport", description="black jansport backpack")
    found = report(color="black", brand="herschel", description="black herschel backpack")
    res = _score(lost, found)
    brand = next(e for e in res.evidence if e["signal"] == "brand")
    assert brand == {"signal": "brand", "text": "Reported brands differ", "direction": "contradicts",
                     "strength": "STRONG", "value": None}


def test_match_api_exposes_evidence(client):
    owner = register(client, "Ayesha Khan", "owner@example.com")
    finder = register(client, "Bilal Ahmed", "finder@example.com")
    lost = client.post("/reports", json=LOST_BACKPACK, headers=owner).json()
    client.post("/reports", json=FOUND_BACKPACK, headers=finder)

    match = client.get(f"/reports/{lost['id']}/matches", headers=owner).json()["matches"][0]
    assert match["evidence"], match
    assert all(e["strength"] in STRENGTHS and e["direction"] in DIRECTIONS for e in match["evidence"])
    supports = [e["text"] for e in match["evidence"] if e["direction"] == "supports"]
    assert match["explanation"][:len(supports)] == supports  # display reasons come from the same items


def test_identical_items_have_no_contradictions():
    a = report(color="black", brand="jansport", description="black jansport backpack")
    b = report(color="black", brand="jansport", description="black jansport backpack")
    res = _score(a, b)
    assert res.concerns == []
    assert all(e["direction"] == "supports" for e in res.evidence)
