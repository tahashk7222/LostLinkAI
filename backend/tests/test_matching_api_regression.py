"""API-level regression tests for matching (Search Again, visual corroboration and the safeguards).

Every case goes through the real endpoints, so persistence, the Search Again route and the lead rules are all exercised.
No thresholds are changed by these tests.
"""

import logging
from datetime import datetime, timedelta, timezone

from app.db.session import SessionLocal
from app.models import MatchCandidate, Notification
from tests.conftest import register
from tests.helpers import FOUND_BACKPACK, LOST_BACKPACK, make_image

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def _iso(dt):
    return dt.isoformat()


def _lost(**kw):
    return {"report_type": "LOST", "category": "Backpack", "name": "Backpack", "description": "Backpack lost near the gate",
            "date_time": _iso(NOW - timedelta(hours=3)), "location": "Gate 3", "place_key": "gate-3", **kw}


def _found(**kw):
    return {"report_type": "FOUND", "category": "Backpack", "name": "Backpack", "description": "Backpack found near the gate",
            "date_time": _iso(NOW - timedelta(hours=1)), "location": "Gate 3", "place_key": "gate-3", **kw}


def _photo(client, headers, rid, data=None):
    r = client.post(f"/reports/{rid}/images", headers=headers,
                    files={"file": ("p.png", data or make_image(fmt="PNG"), "image/png")})
    assert r.status_code == 201, r.text


def _pair(client, lost_body, found_body, same_user=False):
    owner = register(client, "Owner", "owner@example.com")
    finder = owner if same_user else register(client, "Finder", "finder@example.com")
    lost = client.post("/reports", json=lost_body, headers=owner).json()["id"]
    found = client.post("/reports", json=found_body, headers=finder).json()["id"]
    _photo(client, owner, lost)
    _photo(client, finder, found)
    return owner, finder, lost, found


def _search(client, headers, rid):
    r = client.post(f"/reports/{rid}/match", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["matches"]


def _notifications():
    with SessionLocal() as db:
        return db.query(Notification).filter(Notification.type.in_(("match_owner", "match_finder"))).count()


# --- Search Again -----------------------------------------------------------------

def test_search_again_returns_persisted_matches_after_recomputing(client):
    owner, finder, lost, found = _pair(client, _lost(), _found())
    matches = _search(client, owner, lost)
    assert len(matches) == 1
    with SessionLocal() as db:
        assert db.query(MatchCandidate).filter_by(lost_report_id=lost).count() == 1  # persisted
    assert client.get(f"/reports/{lost}/matches", headers=owner).json()["matches"][0]["id"] == matches[0]["id"]


def test_search_again_failure_logs_traceback_and_returns_a_generic_error(client, monkeypatch, caplog):
    from app.api.routes import reports as reports_route

    def broken(db, report):
        raise RuntimeError("simulated scorer failure with internal details")

    monkeypatch.setattr(reports_route, "run_matching", broken)
    owner, finder, lost, found = _pair(client, _lost(), _found())
    with caplog.at_level(logging.ERROR, logger="lostlink.reports"):
        r = client.post(f"/reports/{lost}/match", headers=owner)
    assert r.status_code == 503
    assert "internal details" not in r.text and "RuntimeError" not in r.text  # the client gets no internals
    assert r.json()["detail"].startswith("Matching is temporarily unavailable")
    tracebacks = [rec for rec in caplog.records if "Search again failed" in rec.getMessage() and rec.exc_info]
    assert tracebacks, "the server log must carry the traceback"
    state = client.get(f"/reports/{lost}", headers=owner).json()
    assert state["ai_status"] == "FAILED"  # the UI is told matching failed, not that it succeeded


# --- visual corroboration and its boundaries ------------------------------------------

def test_compatible_visual_pair_is_a_stored_weak_lead_that_never_notifies_or_verifies(client):
    owner, finder, lost, found = _pair(client, _lost(), _found())
    matches = _search(client, owner, lost)
    assert len(matches) == 1 and matches[0]["lead"] == "WEAK"
    assert _notifications() == 0
    assert client.post(f"/matches/{matches[0]['id']}/verification", headers=owner).status_code == 409


def test_visually_similar_items_with_an_incompatible_category_do_not_match(client):
    owner, finder, lost, found = _pair(client, _lost(), _found(category="Laptop", name="Laptop"))
    assert _search(client, owner, lost) == []


def test_visually_similar_items_outside_the_time_window_do_not_match(client):
    owner, finder, lost, found = _pair(client, _lost(), _found(date_time=_iso(NOW - timedelta(days=3))))
    assert _search(client, owner, lost) == []


def test_visually_similar_items_from_the_same_user_do_not_match(client):
    owner, finder, lost, found = _pair(client, _lost(), _found(), same_user=True)
    assert _search(client, owner, lost) == []


def test_a_colour_contradiction_keeps_visually_similar_items_from_matching(client):
    owner, finder, lost, found = _pair(client, _lost(color="black"), _found(color="white"))
    matches = _search(client, owner, lost)
    assert all(m["lead"] == "WEAK" for m in matches)
    assert _notifications() == 0


def test_an_identifier_conflict_keeps_visually_similar_items_from_matching(client):
    owner, finder, lost, found = _pair(client, _lost(distinctive_features="serial 12345 on the strap"),
                                       _found(distinctive_features="serial 99999 on the strap"))
    matches = _search(client, owner, lost)
    assert all(m["lead"] != "STRONG" and m["lead"] != "POSSIBLE" for m in matches)
    assert _notifications() == 0


def test_identity_evidence_still_produces_the_existing_strong_lead(client):
    owner = register(client, "Ayesha Khan", "owner@example.com")
    finder = register(client, "Bilal Ahmed", "finder@example.com")
    lost = client.post("/reports", json=LOST_BACKPACK, headers=owner).json()["id"]
    found = client.post("/reports", json=FOUND_BACKPACK, headers=finder).json()["id"]
    _photo(client, owner, lost)
    _photo(client, finder, found)
    matches = _search(client, owner, lost)
    assert matches and matches[0]["lead"] in ("STRONG", "POSSIBLE")  # identity evidence, unchanged by this pass
    assert matches[0]["lead"] != "WEAK"
