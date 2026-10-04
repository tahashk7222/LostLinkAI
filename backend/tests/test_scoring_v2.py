"""Scoring v2: identity-based leads, context and category never notify alone, labels, caps, limits."""

import dataclasses
from datetime import datetime, timezone
from types import SimpleNamespace

from PIL import Image, ImageDraw

from app.ai import orchestrator
from app.ai.config import get_matching_config
from app.ai.lexical import BM25Index, pair_similarity
from app.ai.matching import score_pair
from app.ai.orchestrator import select_notifiable
from app.ai.providers import get_image_embedder
from app.ai.understanding import understand
from tests.conftest import register
from tests.helpers import FOUND_BACKPACK, LOST_BACKPACK
from tests.test_ai_units import report

WHEN = datetime(2026, 10, 1, 15, tzinfo=timezone.utc)
# These tests pin the v2 rules. The default scorer is v3, which has its own tests in test_scoring_v3.py.
cfg = dataclasses.replace(get_matching_config(), scorer="v2")


def _score(lost, found, text_sim=None):
    return score_pair(lost, found, understand(lost), understand(found), cfg, text_sim=text_sim)


def _with_image(r, spec):
    pic = Image.new("RGB", (240, 240), (235, 235, 235))
    ImageDraw.Draw(pic).rectangle((70, 60, 170, 190), fill=spec)
    r.images = [SimpleNamespace(embedding=get_image_embedder().embed(pic))]
    return r


def test_category_alone_is_not_a_lead():
    lost = report(category="Backpack", name="Backpack", description="a bag", date_time=WHEN)
    found = report(category="Backpack", name="Backpack", description="a bag", date_time=WHEN)
    res = _score(lost, found, text_sim=None)
    assert res.lead is None
    assert res.identity_groups == []


def test_location_time_and_category_together_are_not_a_lead():
    lost = report(category="Backpack", name="Backpack", description="bag", latitude=31.5788, longitude=74.3567,
                  date_time=WHEN, location="Lecture Theatre")
    found = report(category="Backpack", name="Backpack", description="bag", latitude=31.5788, longitude=74.3567,
                   date_time=WHEN, location="Lecture Theatre")
    res = _score(lost, found, text_sim=None)
    assert res.lead is None  # context and category never notify on their own
    assert res.identity_groups == []


def test_visually_similar_photo_alone_is_not_a_lead():
    lost = _with_image(report(category="Backpack", name="Backpack", description="bag", date_time=WHEN), (20, 20, 20))
    found = _with_image(report(category="Backpack", name="Backpack", description="bag", date_time=WHEN), (20, 20, 20))
    res = _score(lost, found, text_sim=None)
    assert res.signals["image"] >= 0.7
    assert res.lead is None


def test_brand_and_colour_alone_is_weak_not_notifiable():
    lost = report(color="black", brand="jansport", description="bag", date_time=WHEN)
    found = report(color="black", brand="jansport", description="bag", date_time=WHEN)
    res = _score(lost, found, text_sim=None)
    assert res.lead == "WEAK"
    assert res.identity_groups == ["brand_model", "colour"]


def test_brand_with_matching_description_is_notifiable():
    lost = report(color="black", brand="jansport", description="bag", date_time=WHEN)
    found = report(color="black", brand="jansport", description="bag", date_time=WHEN)
    res = _score(lost, found, text_sim=0.8)
    assert res.lead in ("STRONG", "POSSIBLE")
    assert {"description", "brand_model", "colour"} <= set(res.identity_groups)


def test_typed_feature_with_colour_is_notifiable():
    lost = report(color="black", description="black bag with red keychain on the zipper", date_time=WHEN)
    found = report(color="black", description="black bag, has a red keychain on the zipper", date_time=WHEN)
    res = _score(lost, found, text_sim=None)
    assert "features" in res.identity_groups
    assert res.lead in ("STRONG", "POSSIBLE")


def test_brand_conflict_caps_the_score_and_is_a_contradiction():
    lost = report(color="black", brand="jansport", description="black bag", date_time=WHEN)
    found = report(color="black", brand="herschel", description="black bag", date_time=WHEN)
    res = _score(lost, found, text_sim=0.9)
    assert res.score <= 0.45
    assert res.caps.get("brand") == 0.45
    assert res.lead is None or res.lead == "WEAK"


def test_accessory_colour_conflict_caps_the_score():
    lost = report(color="black", description="black bag with red keychain", date_time=WHEN)
    found = report(color="black", description="black bag with blue keychain", date_time=WHEN)
    res = _score(lost, found, text_sim=0.9)
    assert res.caps.get("features") == 0.6
    assert any(e["direction"] == "contradicts" and e["signal"] == "features" for e in res.evidence)
    assert res.score <= 0.6


def test_missing_identity_evidence_lowers_the_score():
    base = report(color="black", brand="jansport", description="black bag", date_time=WHEN)
    with_features = report(color="black", brand="jansport", description="black bag with red keychain",
                           date_time=WHEN)
    without = report(color="black", brand="jansport", description="black bag", date_time=WHEN)
    rich = _score(with_features, with_features, text_sim=0.9)
    sparse = _score(without, without, text_sim=None)  # no description or feature comparison possible
    assert rich.coverage > sparse.coverage
    assert rich.score > sparse.score


def test_notifications_are_capped_per_report():
    cfg3 = dataclasses.replace(cfg, max_notifications=3)
    results = [(None, None, SimpleNamespace(lead="POSSIBLE", notify_eligible=True, score=0.9 - i * 0.01))
               for i in range(6)]
    assert len(select_notifiable(results, cfg3)) == 3


def test_weak_leads_are_never_notifiable():
    results = [(None, None, SimpleNamespace(lead="WEAK", notify_eligible=False, score=0.5)),
               (None, None, SimpleNamespace(lead=None, notify_eligible=False, score=0.9))]
    assert select_notifiable(results, cfg) == []


def test_description_similarity_is_absent_when_no_identity_terms():
    lost = SimpleNamespace(description="I lost it, please contact me at 3 pm", distinctive_features=None)
    found = SimpleNamespace(description="found it, contact me", distinctive_features=None)
    index = BM25Index([["red", "wallet"]])
    assert pair_similarity(index, lost, found) is None  # only boilerplate and place words were left


def test_weak_lead_is_stored_but_does_not_notify_or_change_status(client, monkeypatch):
    real = orchestrator.score_candidates

    def weak_only(db, report_obj, cfg_=None):
        results = real(db, report_obj, cfg_)
        for _, _, res in results:
            if res.lead is not None:
                res.lead, res.notify_eligible = "WEAK", False
        return results

    monkeypatch.setattr(orchestrator, "score_candidates", weak_only)
    owner = register(client, "Ayesha Khan", "owner@example.com")
    finder = register(client, "Bilal Ahmed", "finder@example.com")
    lost = client.post("/reports", json=LOST_BACKPACK, headers=owner).json()
    client.post("/reports", json=FOUND_BACKPACK, headers=finder)

    matches = client.get(f"/reports/{lost['id']}/matches", headers=owner).json()["matches"]
    assert [m["lead"] for m in matches] == ["WEAK"]
    assert client.get(f"/reports/{lost['id']}", headers=owner).json()["status"] == "ACTIVE"
    notes = client.get("/notifications", headers=owner).json()["notifications"]
    assert not any(n["type"] == "match_owner" for n in notes)
