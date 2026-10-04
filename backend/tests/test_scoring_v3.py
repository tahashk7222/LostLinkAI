"""Scoring v3: identity-bearing attributes qualify a lead, generic attributes only corroborate.

Three things are kept apart: relevance (score), lead label, and notification eligibility.
"""

import dataclasses
from datetime import datetime, timezone
from types import SimpleNamespace

from PIL import Image, ImageDraw

from app.ai.config import get_matching_config
from app.ai.lexical import BM25Index, description_terms, pair_similarity
from app.ai.matching import generic_identity_terms, score_pair
from app.ai.orchestrator import select_notifiable
from app.ai.providers import get_image_embedder
from app.ai.understanding import understand
from tests.conftest import register
from tests.helpers import FOUND_BACKPACK, LOST_BACKPACK
from tests.test_ai_units import report

WHEN = datetime(2026, 10, 1, 15, tzinfo=timezone.utc)
cfg = get_matching_config()
assert cfg.scorer == "v3"


def _score(lost, found, config=cfg):
    """Mirror orchestrator.score_candidates: description similarity, and the identity variant without accessory wording."""
    lu, fu = understand(lost), understand(found)
    index = BM25Index([description_terms(lost), description_terms(found)])
    text_sim = pair_similarity(index, lost, found)
    identity_sim = pair_similarity(index, lost, found, exclude=generic_identity_terms(lost, lu) | generic_identity_terms(found, fu))
    return score_pair(lost, found, lu, fu, config, text_sim=text_sim, identity_sim=identity_sim)


def _with_image(r, spec):
    pic = Image.new("RGB", (240, 240), (235, 235, 235))
    ImageDraw.Draw(pic).rectangle((70, 60, 170, 190), fill=spec)
    r.images = [SimpleNamespace(embedding=get_image_embedder().embed(pic))]
    return r


def _same_spot(**kw):
    return dict(date_time=WHEN, location="Lecture Theatre", latitude=31.5788, longitude=74.3567, **kw)


def test_category_location_time_and_colour_are_not_identity():
    lost = report(category="Backpack", name="Backpack", color="black", description="bag", **_same_spot())
    found = report(category="Backpack", name="Backpack", color="black", description="bag", **_same_spot())
    res = _score(lost, found)
    assert res.lead in (None, "WEAK")  # colour is corroboration only, so it is at most Weak
    assert res.identity_groups == []
    assert res.notify_eligible is False


def test_brand_and_colour_alone_is_weak_and_not_notifiable():
    lost = report(category="Backpack", name="Backpack", color="black", brand="JanSport",
                  description="black JanSport backpack", **_same_spot())
    found = report(category="Bag", name="Backpack", color="black", brand="Jansport",
                   description="black JanSport bag", **_same_spot())
    res = _score(lost, found)
    assert res.lead == "WEAK"
    assert res.identity_groups == []  # a common brand is not identity on its own
    assert "brand" in res.corroborating and "colour" in res.corroborating
    assert res.notify_eligible is False


def test_key_ring_with_common_brand_and_shared_accessory_wording_is_weak():
    """The v2 false positive: a common brand, colour and the same accessory phrase on two different key rings."""
    lost = report(category="Keys", name="Silver keys", color="silver", brand="Honda",
                  description="silver Honda keys with football shaped keychain", distinctive_features="football shaped keychain",
                  **_same_spot())
    found = report(category="Key ring", name="Silver keys", color="silver", brand="Honda",
                   description="silver Honda keys, it has football shaped keychain", distinctive_features=None,
                   **_same_spot())
    res = _score(lost, found)
    assert res.lead == "WEAK"
    assert "description" not in res.identity_groups  # the shared words are accessory wording, not identity
    assert res.notify_eligible is False


def test_custom_keychain_with_marking_and_brand_is_notifiable():
    lost = report(category="Backpack", name="Backpack", color="black", brand="JanSport",
                  description="black JanSport backpack", distinctive_features="name tag with initials inside the pocket",
                  **_same_spot())
    found = report(category="Bag", name="Backpack", color="black", brand="Jansport",
                   description="black JanSport bag", distinctive_features="has a name tag with initials inside the pocket",
                   **_same_spot())
    res = _score(lost, found)
    assert res.lead in ("STRONG", "POSSIBLE")
    assert "features" in res.identity_groups
    assert res.notify_eligible is True


def test_shared_model_code_with_colour_is_identity():
    lost = report(category="Watch", name="Watch", color="black", description="black Casio F-91W watch",
                  **_same_spot())
    found = report(category="Watch", name="Watch", color="black", description="found a black Casio F-91W",
                   **_same_spot())
    res = _score(lost, found)
    assert "model" in res.identity_groups
    assert res.lead in ("STRONG", "POSSIBLE")
    assert res.notify_eligible is True


def test_colour_and_distinctive_description_is_possible():
    lost = report(category="Backpack", name="Backpack", color="black",
                  description="black bag with calculus notebook", **_same_spot())
    found = report(category="Bag", name="Backpack", color="black",
                   description="black bag, calculus notebook inside", **_same_spot())
    res = _score(lost, found)
    assert "description" in res.identity_groups
    assert res.lead in ("STRONG", "POSSIBLE")
    assert res.notify_eligible is True


def test_different_brand_with_matching_marking_is_not_notifiable():
    """A brand conflict caps the relevance score, so the pair cannot become a Possible lead."""
    lost = report(category="Backpack", name="Backpack", color="black", brand="JanSport",
                  description="black JanSport backpack", distinctive_features="name tag with initials inside the pocket",
                  **_same_spot())
    found = report(category="Bag", name="Backpack", color="black", brand="Herschel",
                   description="black Herschel bag", distinctive_features="name tag with initials inside the pocket",
                   **_same_spot())
    res = _score(lost, found)
    assert res.lead != "POSSIBLE" and res.lead != "STRONG"
    assert res.notify_eligible is False
    assert any(e["direction"] == "contradicts" and e["signal"] == "brand" for e in res.evidence)


def test_visually_similar_photo_alone_never_notifies():
    lost = _with_image(report(category="Backpack", name="Backpack", color="black", description="bag", **_same_spot()),
                       (20, 20, 20))
    found = _with_image(report(category="Bag", name="Backpack", color="black", description="bag", **_same_spot()),
                        (20, 20, 20))
    res = _score(lost, found)
    assert res.signals["image"] >= 0.7
    assert res.notify_eligible is False
    assert res.lead in (None, "WEAK")


def test_relevance_is_reported_even_when_the_lead_is_not_notifiable():
    """Relevance ranks candidates and can be high while the lead stays Weak. The two are separate fields."""
    lost = report(category="Backpack", name="Backpack", color="black", brand="JanSport", description="black bag",
                  **_same_spot())
    found = report(category="Bag", name="Backpack", color="black", brand="Jansport", description="black bag",
                   **_same_spot())
    res = _score(lost, found)
    assert res.score > 0
    assert res.lead == "WEAK" and res.notify_eligible is False


def test_select_notifiable_follows_the_eligibility_flag_not_the_label():
    results = [(None, None, SimpleNamespace(lead="STRONG", notify_eligible=True, score=0.9)),
               (None, None, SimpleNamespace(lead="WEAK", notify_eligible=False, score=0.8)),
               (None, None, SimpleNamespace(lead="POSSIBLE", notify_eligible=True, score=0.7))]
    picked = select_notifiable(results, dataclasses.replace(cfg, max_notifications=5))
    assert [r[2].lead for r in picked] == ["STRONG", "POSSIBLE"]


def test_v1_fallback_still_available():
    v1 = dataclasses.replace(cfg, scorer="v1")
    lost = report(category="Backpack", name="Backpack", color="black", brand="JanSport", description="black bag",
                  **_same_spot())
    found = report(category="Backpack", name="Backpack", color="black", brand="JanSport", description="black bag",
                   **_same_spot())
    res = _score(lost, found, config=v1)
    assert res.lead == "POSSIBLE" and res.notify_eligible is True


def test_weak_lead_cannot_start_verification(client):
    owner = register(client, "Ayesha Khan", "owner@example.com")
    finder = register(client, "Bilal Ahmed", "finder@example.com")
    weak_lost = dict(LOST_BACKPACK, distinctive_features="Red keychain on the front zipper")
    weak_found = dict(FOUND_BACKPACK, distinctive_features="Has a red keychain attached to the zipper")
    lost = client.post("/reports", json=weak_lost, headers=owner).json()
    client.post("/reports", json=weak_found, headers=finder)
    match = client.get(f"/reports/{lost['id']}/matches", headers=owner).json()["matches"][0]
    assert match["lead"] == "WEAK"
    resp = client.post(f"/matches/{match['id']}/verification", headers=owner)
    assert resp.status_code == 409
    assert "Weak lead cannot start ownership verification" in resp.json()["detail"]
    # A Weak lead can still be dismissed by the owner.
    assert client.post(f"/matches/{match['id']}/dismiss", headers=owner).status_code == 200
