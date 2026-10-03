from datetime import datetime, timezone
from types import SimpleNamespace

from app.ai.config import get_matching_config
from app.ai.matching import haversine_km, score_pair
from app.ai.providers import cosine, get_text_embedder
from app.ai.understanding import extract_brand, extract_colors, normalize_category, understand
from app.ai.verification import build_questions, evaluate_answers
from app.models.enums import AttributeSource


def report(**kw):
    base = dict(category="Backpack", name="Backpack", description="A bag", color=None, brand=None, model=None,
                distinctive_features=None, private_details=None, location="Library", latitude=None,
                longitude=None, date_time=datetime(2026, 10, 1, 15, tzinfo=timezone.utc), images=[])
    base.update(kw)
    r = SimpleNamespace(**base)
    r.text_embedding = get_text_embedder().embed(f"{r.category} {r.name} {r.description} {r.distinctive_features or ''}")
    return r


def test_category_normalisation():
    assert normalize_category("rucksack")[0] == "backpack"
    assert normalize_category("my iPhone 13")[0] == "phone"
    assert normalize_category("laptop bag")[0] == "laptop bag"  # longest synonym wins over "laptop"
    assert normalize_category("strange gadget")[1] == "other"


def test_colour_and_brand_extraction():
    assert extract_colors("navy blue jacket with grey stripes") == {"blue", "gray"}
    assert extract_brand("my samsung galaxy") == "samsung"
    assert extract_brand("a plain bag") is None


def test_understanding_marks_sources():
    u = understand(report(color="Black", description="black bag with a Nike logo and a red keychain"))
    by = {(a.name, a.value): a.source for a in u.attributes}
    assert by[("color", "black")] == AttributeSource.USER
    assert by[("color", "red")] == AttributeSource.AI
    assert by[("brand", "nike")] == AttributeSource.AI
    assert any(a.name == "feature" for a in u.attributes)


def test_text_embedding_similarity_not_exact_match():
    e = get_text_embedder().embed
    a = e("black backpack with red keychain")
    b = e("Black back-pack, has a red key chain")
    c = e("silver samsung phone")
    assert cosine(a, b) > cosine(a, c)
    assert cosine(a, a) > 0.99


def test_haversine():
    assert 1.0 < haversine_km(33.6425, 72.9930, 33.6525, 72.9930) < 1.2


def test_matching_ranks_true_match_higher():
    cfg = get_matching_config()
    lost = report(color="black", brand="jansport", description="black jansport backpack lost at library",
                  distinctive_features="red keychain", latitude=33.6425, longitude=72.9930)
    good = report(category="bag", color="black", brand="jansport", description="found black jansport backpack",
                  distinctive_features="red keychain on zipper", latitude=33.6431, longitude=72.9941,
                  date_time=datetime(2026, 10, 1, 15, 30, tzinfo=timezone.utc))
    bad = report(category="phone", name="phone", color="silver", brand="samsung", description="silver samsung phone",
                 latitude=33.70, longitude=73.10, date_time=datetime(2026, 10, 5, tzinfo=timezone.utc))
    g = score_pair(lost, good, understand(lost), understand(good), cfg)
    b = score_pair(lost, bad, understand(lost), understand(bad), cfg)
    assert g.score >= cfg.threshold > b.score
    assert any("Same item category" in r for r in g.reasons)
    assert any(" m from where it was lost" in r for r in g.reasons)
    assert any("minutes" in r for r in g.reasons)
    assert b.score <= 0.4  # category contradiction caps the score


def test_found_before_lost_is_penalised():
    cfg = get_matching_config()
    lost = report(date_time=datetime(2026, 10, 3, tzinfo=timezone.utc))
    found = report(date_time=datetime(2026, 9, 25, tzinfo=timezone.utc))
    res = score_pair(lost, found, understand(lost), understand(found), cfg)
    assert res.signals["time"] == 0.0
    assert any("before" in c for c in res.concerns)


def test_weights_are_configurable(monkeypatch):
    monkeypatch.setenv("MATCH_WEIGHT_LOCATION", "0")
    assert get_matching_config().weights["location"] == 0


def test_verification_questions_and_advisory_score():
    found = report(category="backpack", description="black backpack", private_details="blue calculus notebook and casio calculator")
    qs = build_questions(found)
    assert any(q["id"] == "contents" for q in qs)
    good, notes = evaluate_answers(found, qs, {"contents": "A blue notebook with calculus notes, a Casio calculator"})
    weak, _ = evaluate_answers(found, qs, {"contents": "a black backpack"})
    assert good > weak
    assert any("advisory" in n for n in notes)
    # notes never quote the private details
    assert not any("calculus" in n.lower() for n in notes)
