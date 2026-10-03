"""Private details must never appear in match output, explanations or evidence.

Each report carries unique canary strings in `private_details`. The canaries are chosen so
they do not occur in any public field. Every match-facing output is then checked for them:
API responses for owner, finder and admin, notifications, stored suggestions, and the
scorer's own inputs and outputs.
"""

import json
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import select

from app.ai.config import get_matching_config
from app.ai.matching import score_pair
from app.ai.understanding import embedding_text, understand
from app.db.session import SessionLocal
from app.models import MatchCandidate, User
from app.models.enums import Role
from tests.conftest import register
from tests.helpers import FOUND_BACKPACK, LOST_BACKPACK

CANARIES = ["canary-ledger-9q7", "kestrel-42", "lavender-sticker-x1"]
LOST_PRIVATE = "Inside the bag: canary-ledger-9q7 notebook and a lavender-sticker-x1 pouch."
FOUND_PRIVATE = "Owner details written on card: kestrel-42, do not share."


def _assert_no_canary(payload, where: str):
    text = payload if isinstance(payload, str) else json.dumps(payload, default=str)
    for canary in CANARIES:
        assert canary not in text.lower(), f"private canary {canary!r} leaked into {where}"


def _setup(client):
    owner = register(client, "Ayesha Khan", "owner@example.com")
    finder = register(client, "Bilal Ahmed", "finder@example.com")
    admin = register(client, "Admin Person", "admin@example.com")
    with SessionLocal() as db:
        db.query(User).filter(User.email == "admin@example.com").one().role = Role.ADMIN
        db.commit()
    lost = client.post("/reports", json={**LOST_BACKPACK, "private_details": LOST_PRIVATE}, headers=owner).json()
    found = client.post("/reports", json={**FOUND_BACKPACK, "private_details": FOUND_PRIVATE},
                        headers=finder).json()
    return owner, finder, admin, lost, found


def test_private_details_absent_from_match_api_for_every_role(client):
    owner, finder, admin, lost, found = _setup(client)

    listing = client.get(f"/reports/{lost['id']}/matches", headers=owner).json()
    assert listing["matches"], "the pair must be matched for this test to mean anything"
    _assert_no_canary(listing, "owner's match listing")

    match_id = listing["matches"][0]["id"]
    _assert_no_canary(client.get(f"/matches/{match_id}", headers=owner).json(), "owner match detail")
    _assert_no_canary(client.get(f"/matches/{match_id}", headers=finder).json(), "finder match detail")
    _assert_no_canary(client.get(f"/matches/{match_id}", headers=admin).json(), "admin match detail")
    _assert_no_canary(client.get("/matches", headers=owner).json(), "owner's matches")
    _assert_no_canary(client.get("/matches", headers=finder).json(), "finder's matches")
    _assert_no_canary(client.post(f"/reports/{lost['id']}/match", headers=owner).json(), "re-run response")


def test_private_details_absent_from_notifications(client):
    owner, finder, admin, lost, found = _setup(client)
    for headers in (owner, finder):
        _assert_no_canary(client.get("/notifications", headers=headers).json(), "notifications")


def test_private_details_absent_from_stored_suggestions(client):
    owner, finder, admin, lost, found = _setup(client)
    with SessionLocal() as db:
        rows = db.scalars(select(MatchCandidate)).all()
        assert rows, "the pair must be matched for this test to mean anything"
        for m in rows:
            _assert_no_canary(m.explanation, "stored explanation")
            _assert_no_canary(m.evidence, "stored evidence")
            _assert_no_canary(m.signals, "stored signals")


def test_private_details_do_not_enter_understanding_or_embedding_text():
    lost = SimpleNamespace(category="Backpack", name="Black backpack", description="Black bag, red keychain",
                           color="black", brand=None, model=None, distinctive_features=None,
                           private_details=LOST_PRIVATE)
    u = understand(lost)
    assert all(not any(c in str(a.value).lower() for c in CANARIES) for a in u.attributes)
    assert not any(c in embedding_text(lost).lower() for c in CANARIES)


def test_scorer_output_never_contains_private_details():
    cfg = get_matching_config()
    when = datetime(2026, 10, 1, 15, tzinfo=timezone.utc)
    lost = SimpleNamespace(category="Backpack", name="Black backpack", description="Black bag, red keychain",
                           color="black", brand="jansport", model=None, distinctive_features="red keychain",
                           private_details=LOST_PRIVATE, location="Library", latitude=33.6425,
                           longitude=72.9930, place_key=None, zone="campus", date_time=when, images=[],
                           text_embedding=None)
    found = SimpleNamespace(category="Bag", name="Black backpack", description="Black bag with red keychain",
                            color="black", brand="jansport", model=None, distinctive_features="red keychain",
                            private_details=FOUND_PRIVATE, location="Bench", latitude=33.6431,
                            longitude=72.9941, place_key=None, zone="campus", date_time=when, images=[],
                            text_embedding=None)
    from app.ai.providers import get_text_embedder
    lost.text_embedding = get_text_embedder().embed(embedding_text(lost))
    found.text_embedding = get_text_embedder().embed(embedding_text(found))
    res = score_pair(lost, found, understand(lost), understand(found), cfg)
    _assert_no_canary(res.explanation, "scorer explanation")
    _assert_no_canary(res.evidence, "scorer evidence")
    _assert_no_canary(res.signals, "scorer signals")
