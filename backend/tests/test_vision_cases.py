"""The seven integration cases from the CV brief, run through the REAL matcher (score_pair) with the learned model.

Visual evidence is corroboration only. These tests assert the existing identity and notification rules still hold
when the visual signal is strong: a visual match never creates identity, never creates a Strong or Possible lead on
its own, and never notifies. Model-dependent cases are skipped when the model file is not installed.
"""

import dataclasses
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from app.ai import providers
from app.ai.config import get_matching_config
from app.ai.providers import image_method
from app.ai.providers import vision as vision_mod
from app.ai.providers.image import HeuristicImageEmbedder
from app.ai.providers.vision import default_model_path
from app.ai.visual import visual_evidence
from tests.test_ai_units import report
from tests.test_scoring_v3 import _same_spot, _score

MODEL_PRESENT = default_model_path().is_file()
needs_model = pytest.mark.skipif(not MODEL_PRESENT, reason="model file missing: run python -m scripts.fetch_vision_model")


def _wallet(colour, marks, bg=(235, 235, 235), offset=(0, 0)):
    img = Image.new("RGB", (240, 240), bg)
    d = ImageDraw.Draw(img)
    x0, y0 = 50 + offset[0], 80 + offset[1]
    d.rounded_rectangle((x0, y0, x0 + 140, y0 + 80), radius=14, fill=colour)
    for k in range(marks):
        d.line((x0 + 20 + 18 * k, y0 + 15, x0 + 20 + 18 * k, y0 + 65), fill=(colour[0] + 60, colour[1] + 60, colour[2] + 60), width=3)
    return img


def _bag(colour, bg=(235, 235, 235)):
    img = Image.new("RGB", (240, 240), bg)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((60, 50, 180, 200), radius=26, fill=colour)
    d.line((80, 60, 80, 110), fill=(30, 30, 30), width=5)
    d.line((160, 60, 160, 110), fill=(30, 30, 30), width=5)
    return img


def _laptop(colour, bg=(235, 235, 235)):
    img = Image.new("RGB", (240, 240), bg)
    d = ImageDraw.Draw(img)
    d.rectangle((40, 70, 200, 170), fill=colour)
    d.rectangle((52, 82, 188, 158), fill=(30, 40, 60))
    d.rectangle((20, 170, 220, 186), fill=(150, 150, 150))
    return img


@pytest.fixture
def learned(monkeypatch):
    if not MODEL_PRESENT:
        pytest.skip("model file missing")
    providers._learned_embedder.cache_clear()
    yield providers.get_image_embedder()
    providers._learned_embedder.cache_clear()


def _with_photo(r, img, embedder):
    r.images = [SimpleNamespace(embedding=embedder.embed(img))]
    return r


def _pair(embedder, lost_img, found_img, *, lost_kw=None, found_kw=None):
    base = dict(category="Wallet", name="Wallet", description="wallet", color=None, brand=None, **_same_spot())
    lost = _with_photo(report(**{**base, **(lost_kw or {})}), lost_img, embedder)
    found = _with_photo(report(**{**base, **(found_kw or {})}), found_img, embedder)
    return lost, found


# CASE A: the same physical object, photographed at a different angle and lighting.
@needs_model
def test_case_a_same_object_gives_high_visual_similarity_but_still_needs_identity(learned):
    lost_img = _wallet((30, 30, 30), marks=2)
    found_img = _wallet((30, 30, 30), marks=2, bg=(200, 215, 230), offset=(4, 3))
    lost, found = _pair(learned, lost_img, found_img)
    res = _score(lost, found)
    assert res.signals["image"] >= 0.8
    assert res.notify_eligible is False  # no shared identity text or feature: visual evidence alone never notifies
    assert "features" not in res.identity_groups


# CASE B: two different black wallets. Visual similarity may be high; the identity safeguards must still hold.
@needs_model
def test_case_b_two_different_black_wallets_are_not_identified_by_appearance(learned):
    lost_img = _wallet((25, 25, 25), marks=2)
    found_img = _wallet((25, 25, 25), marks=4, bg=(200, 215, 230))  # different stitching, same colour and shape
    lost, found = _pair(learned, lost_img, found_img, lost_kw=dict(color="black"), found_kw=dict(color="black"))
    res = _score(lost, found)
    assert res.notify_eligible is False
    assert res.lead in (None, "WEAK")
    assert res.identity_groups == []  # category and colour are not identity; the photos do not add identity either


# CASE C: same brand, different object. Visual evidence does not establish identity.
@needs_model
def test_case_c_same_brand_different_object_is_not_identity(learned):
    lost_img = _bag((40, 60, 150))
    found_img = _bag((40, 60, 150), bg=(200, 215, 230))
    lost, found = _pair(learned, lost_img, found_img, lost_kw=dict(category="Bag", brand="JanSport", color="blue"),
                        found_kw=dict(category="Bag", brand="JanSport", color="blue"))
    res = _score(lost, found)
    assert res.notify_eligible is False
    assert res.lead in (None, "WEAK")
    assert "brand" in res.corroborating and "brand" not in res.identity_groups


# CASE D: unrelated objects. Visual similarity is low and nothing notifies.
@needs_model
def test_case_d_unrelated_objects_have_low_visual_similarity(learned):
    lost_img = _bag((180, 40, 40))
    found_img = _laptop((60, 60, 60))
    lost, found = _pair(learned, lost_img, found_img, lost_kw=dict(category="Bag", color="red"),
                        found_kw=dict(category="Laptop", color="grey"))
    res = _score(lost, found)
    assert res.signals.get("image", 0.0) < 0.7
    assert res.notify_eligible is False


# CASE E: no image on either report. Matching continues from the non-image signals.
def test_case_e_no_photos_matching_continues_without_a_visual_signal():
    lost = report(category="Wallet", name="Wallet", description="black wallet with a red keychain", color="black",
                  distinctive_features="red keychain on the zipper", **_same_spot())
    found = report(category="Wallet", name="Wallet", description="black wallet with a red keychain", color="black",
                   distinctive_features="has a red keychain on the zipper", **_same_spot())
    lost.images, found.images = [], []
    res = _score(lost, found)
    assert "image" not in res.signals
    assert res.score > 0  # the other signals still produce a relevance value
    assert visual_evidence([], [])["available"] is False


# CASE F: the learned model disabled by settings. The application keeps working on the heuristic.
def test_case_f_model_disabled_matching_works_on_the_heuristic(monkeypatch):
    providers._learned_embedder.cache_clear()
    monkeypatch.setattr(providers.get_settings(), "vision_enabled", False)
    embedder = providers.get_image_embedder()
    assert image_method(embedder) == "heuristic"
    lost = report(category="Wallet", name="Wallet", description="black wallet", color="black", **_same_spot())
    found = report(category="Wallet", name="Wallet", description="black wallet", color="black", **_same_spot())
    lost.images = [SimpleNamespace(embedding=embedder.embed(_wallet((25, 25, 25), marks=2)))]
    found.images = [SimpleNamespace(embedding=embedder.embed(_wallet((25, 25, 25), marks=2)))]
    res = _score(lost, found)
    assert "image" in res.signals  # the heuristic still contributes visual evidence
    providers._learned_embedder.cache_clear()


# CASE G: the learned model fails to load. Matching still runs, with the heuristic.
def test_case_g_model_failure_matching_works_on_the_heuristic(monkeypatch):
    providers._learned_embedder.cache_clear()
    monkeypatch.setattr(providers.get_settings(), "vision_enabled", True)
    monkeypatch.setattr(vision_mod.OnnxVisionEmbedder, "load",
                        classmethod(lambda cls, *a, **k: (_ for _ in ()).throw(vision_mod.VisionUnavailable("broken"))))
    embedder = providers.get_image_embedder()
    assert isinstance(embedder, HeuristicImageEmbedder)
    lost = report(category="Wallet", name="Wallet", description="black wallet", color="black", **_same_spot())
    found = report(category="Wallet", name="Wallet", description="black wallet", color="black", **_same_spot())
    lost.images = [SimpleNamespace(embedding=embedder.embed(_wallet((25, 25, 25), marks=2)))]
    found.images = [SimpleNamespace(embedding=embedder.embed(_wallet((25, 25, 25), marks=2)))]
    assert _score(lost, found).notify_eligible is False  # no identity, so no notification, and no crash
    providers._learned_embedder.cache_clear()


def test_policy_constants_are_unchanged():
    """The visual change must not move any matching threshold or weight."""
    from app.ai import matching
    cfg = get_matching_config()
    assert matching.VISUAL_CORROBORATION == 0.7
    assert matching.W_V2["image"] == 0.08
    assert cfg.threshold == 0.55 and cfg.strong_score == 0.75 and cfg.weak_score == 0.35
    assert cfg.max_notifications == 3
