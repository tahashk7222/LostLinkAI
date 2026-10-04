"""Regression tests for the production report "White Charger" that showed "No potential matches yet".

Diagnosis (reproduced through the API on SQLite and PostgreSQL 16, see the report notes):
- A compatible pair (different accounts, found 1 h after the loss, same place) IS a candidate.
  It scores as a WEAK lead: category, colour, place, time and photos corroborate, but no identity group
  (marking, damage, model, distinctive description) exists, so it cannot be Possible or Strong and cannot notify.
- The same pair produces no candidate at all when the found report's time is more than 12 hours before the
  lost report's time (retrieval window), or when both reports belong to the same account (reporter filter).
  Search again then correctly returns an empty list.

These tests lock that behaviour: the compatible pair is evaluated and shown as WEAK, Search again recomputes
from current data, and the safeguards that stop a non-identity pair from notifying remain in force.
"""

from app.db.session import SessionLocal
from app.models import Notification
from tests.conftest import register
from tests.helpers import make_image

LOST_CHARGER = {
    "report_type": "LOST", "category": "Charger", "name": "Charger", "description": "White charger",
    "color": "White", "private_details": "Charger cable is 1 metre long",
    "date_time": "2026-10-04T18:00:00Z",  # 11 PM in Pakistan (UTC+5)
    "location": "Gate 3", "place_key": "gate-3",
}


def found_charger(date_time, color="White"):
    return {
        "report_type": "FOUND", "category": "Charger", "name": "White Charger", "description": "White charger",
        "color": color, "date_time": date_time, "location": "Gate 3", "place_key": "gate-3",
    }


def add_photos(client, headers, report_id):
    for _ in range(2):
        r = client.post(f"/reports/{report_id}/images", headers=headers,
                        files={"file": ("charger.png", make_image(fmt="PNG"), "image/png")})
        assert r.status_code == 201, r.text


def search_again(client, headers, report_id):
    r = client.post(f"/reports/{report_id}/match", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["matches"]


def match_notifications() -> int:
    with SessionLocal() as db:
        return db.query(Notification).filter(Notification.type.in_(("match_owner", "match_finder"))).count()


def test_compatible_charger_pair_is_evaluated_and_shown_as_weak_not_notified(client):
    owner = register(client, "Owner", "owner@example.com")
    finder = register(client, "Finder", "finder@example.com")
    lost = client.post("/reports", json=LOST_CHARGER, headers=owner).json()["id"]
    found = client.post("/reports", json=found_charger("2026-10-04T19:02:00Z"), headers=finder).json()["id"]
    add_photos(client, owner, lost)
    add_photos(client, finder, found)

    matches = search_again(client, owner, lost)

    assert len(matches) == 1, "a compatible charger pair must be evaluated as a candidate"
    m = matches[0]
    assert m["lead"] == "WEAK"  # colour, category, place, time and photos corroborate; no identity group
    assert m["signals"]["category"] == 1.0 and m["signals"]["color"] == 1.0
    assert match_notifications() == 0  # a Weak lead never notifies
    # A Weak lead cannot start ownership verification, even when requested directly.
    assert client.post(f"/matches/{m['id']}/verification", headers=owner).status_code == 409


def test_found_more_than_twelve_hours_before_the_loss_is_not_a_candidate(client):
    owner = register(client, "Owner", "owner@example.com")
    finder = register(client, "Finder", "finder@example.com")
    lost = client.post("/reports", json=LOST_CHARGER, headers=owner).json()["id"]
    # Same calendar date as the loss but 12:02 AM: 23 hours before the 11 PM loss.
    client.post("/reports", json=found_charger("2026-10-03T19:02:00Z"), headers=finder)
    assert search_again(client, owner, lost) == []


def test_same_account_reports_are_never_matched_with_each_other(client):
    owner = register(client, "Owner", "owner@example.com")
    lost = client.post("/reports", json=LOST_CHARGER, headers=owner).json()["id"]
    client.post("/reports", json=found_charger("2026-10-04T19:02:00Z"), headers=owner)
    assert search_again(client, owner, lost) == []


def test_search_again_recomputes_from_current_reports(client):
    owner = register(client, "Owner", "owner@example.com")
    finder = register(client, "Finder", "finder@example.com")
    lost = client.post("/reports", json=LOST_CHARGER, headers=owner).json()["id"]
    found = client.post("/reports", json=found_charger("2026-10-03T19:02:00Z"), headers=finder).json()["id"]
    assert search_again(client, owner, lost) == []

    # The finder corrects the time. Search again must now evaluate the pair; nothing stale is returned.
    assert client.put(f"/reports/{found}", json={"date_time": "2026-10-04T19:02:00Z"}, headers=finder).status_code == 200
    matches = search_again(client, owner, lost)
    assert len(matches) == 1 and matches[0]["lead"] == "WEAK"


def test_colour_conflict_keeps_the_pair_from_notifying(client):
    owner = register(client, "Owner", "owner@example.com")
    finder = register(client, "Finder", "finder@example.com")
    lost = client.post("/reports", json=LOST_CHARGER, headers=owner).json()["id"]
    client.post("/reports", json=found_charger("2026-10-04T19:02:00Z", color="Black"), headers=finder)
    matches = search_again(client, owner, lost)
    assert all(m["lead"] == "WEAK" for m in matches)  # never Strong or Possible on a colour conflict
    assert match_notifications() == 0


def test_embedding_failure_is_logged_and_upload_still_succeeds(client, monkeypatch, caplog):
    import logging

    from app.api.routes import reports as reports_route

    class BrokenEmbedder:
        name = "broken"

        def embed(self, img):
            raise RuntimeError("simulated inference failure")

    monkeypatch.setattr(reports_route, "get_image_embedder", lambda: BrokenEmbedder())
    owner = register(client, "Owner", "owner@example.com")
    lost = client.post("/reports", json=LOST_CHARGER, headers=owner).json()["id"]
    with caplog.at_level(logging.WARNING, logger="lostlink.reports"):
        r = client.post(f"/reports/{lost}/images", headers=owner,
                        files={"file": ("charger.png", make_image(fmt="PNG"), "image/png")})
    assert r.status_code == 201  # the photo is kept; matching continues without the visual signal
    assert any("image embedding failed" in rec.getMessage() for rec in caplog.records)
