"""Stale-match handling and concurrency of the matching pipeline."""

import dataclasses
import threading
import time

from sqlalchemy import select

from app.ai import orchestrator
from app.ai.config import get_matching_config
from app.ai.orchestrator import process_report
from app.db.session import SessionLocal
from app.models import ItemReport, MatchCandidate
from app.models.enums import AIStatus, ReportStatus
from tests.conftest import register
from tests.helpers import FOUND_BACKPACK, LOST_BACKPACK


def _pair(client, owner_name="Ayesha", owner_email="owner@example.com"):
    owner = register(client, owner_name, owner_email)
    finder = register(client, "Bilal Ahmed", "finder@example.com")
    lost = client.post("/reports", json=LOST_BACKPACK, headers=owner).json()
    found = client.post("/reports", json=FOUND_BACKPACK, headers=finder).json()
    return owner, finder, lost, found


def _matches(client, headers, report_id):
    return client.get(f"/reports/{report_id}/matches", headers=headers).json()["matches"]


def _report_status(client, headers, report_id):
    return client.get(f"/reports/{report_id}", headers=headers).json()["status"]


def test_match_is_withdrawn_when_finder_changes_item_type(client):
    owner, finder, lost, found = _pair(client)
    assert len(_matches(client, owner, lost["id"])) == 1

    r = client.put(f"/reports/{found['id']}", headers=finder,
                   json={"category": "Laptop", "name": "Silver laptop", "color": "silver", "brand": None,
                         "description": "Found a silver laptop on a bench."})
    assert r.status_code == 200, r.text

    assert _matches(client, owner, lost["id"]) == []
    assert _report_status(client, owner, lost["id"]) == "ACTIVE"


def test_closing_the_other_report_withdraws_the_match(client):
    owner, finder, lost, found = _pair(client)
    assert len(_matches(client, owner, lost["id"])) == 1

    r = client.put(f"/reports/{found['id']}", headers=finder, json={"status": "CLOSED"})
    assert r.status_code == 200, r.text

    assert _matches(client, owner, lost["id"]) == []
    assert _report_status(client, owner, lost["id"]) == "ACTIVE"


def test_closing_own_report_withdraws_its_suggestions(client):
    owner, finder, lost, found = _pair(client)
    r = client.put(f"/reports/{lost['id']}", headers=owner, json={"status": "CLOSED"})
    assert r.status_code == 200, r.text
    assert _matches(client, finder, found["id"]) == []


def test_matches_in_verification_are_not_withdrawn(client, monkeypatch):
    owner, finder, lost, found = _pair(client)
    match = _matches(client, owner, lost["id"])[0]
    assert client.post(f"/matches/{match['id']}/verification", headers=owner).status_code == 201

    # Even if the pair stops qualifying, a suggestion a person is verifying is left alone.
    monkeypatch.setattr(orchestrator, "get_matching_config",
                        lambda: dataclasses.replace(get_matching_config(), threshold=0.99))
    assert client.post(f"/reports/{lost['id']}/match", headers=owner).status_code == 200
    assert [m["id"] for m in _matches(client, owner, lost["id"])] == [match["id"]]


def test_suggestion_below_threshold_is_withdrawn_on_rerun(client, monkeypatch):
    owner, finder, lost, found = _pair(client)
    assert len(_matches(client, owner, lost["id"])) == 1

    # Raise both floors: a pair that still qualifies as a Weak lead is kept, so it must fall below weak too.
    monkeypatch.setattr(orchestrator, "get_matching_config",
                        lambda: dataclasses.replace(get_matching_config(), threshold=0.99, weak_score=0.99))
    r = client.post(f"/reports/{lost['id']}/match", headers=owner)
    assert r.status_code == 200, r.text
    assert r.json()["matches"] == []
    assert _matches(client, owner, lost["id"]) == []
    assert _report_status(client, owner, lost["id"]) == "ACTIVE"


def test_dismissed_match_is_not_returned_or_resurfaced(client):
    owner, finder, lost, found = _pair(client)
    match = _matches(client, owner, lost["id"])[0]
    assert client.post(f"/matches/{match['id']}/dismiss", headers=owner).status_code == 200

    rerun = client.post(f"/reports/{lost['id']}/match", headers=owner)
    assert rerun.status_code == 200, rerun.text
    assert rerun.json()["matches"] == []
    assert _matches(client, owner, lost["id"]) == []


def test_connecting_one_match_withdraws_competing_suggestions(client):
    ayesha, finder, lost_a, found = _pair(client, "Ayesha", "ayesha@example.com")
    zara = register(client, "Zara Malik", "zara@example.com")
    lost_z = client.post("/reports", json=LOST_BACKPACK, headers=zara).json()
    assert len(_matches(client, zara, lost_z["id"])) == 1  # competing claim for the same found item

    match = _matches(client, ayesha, lost_a["id"])[0]
    assert client.post(f"/matches/{match['id']}/verification", headers=ayesha).status_code == 201
    assert client.post(f"/matches/{match['id']}/verification/answers", headers=ayesha, json={"answers": {
        "contents": "A blue calculus notebook, a Casio calculator and a green water bottle"}}).status_code == 200
    r = client.post(f"/matches/{match['id']}/verify", headers=finder, json={"decision": "ACCEPT"})
    assert r.status_code == 200, r.text

    assert _matches(client, zara, lost_z["id"]) == []
    assert _report_status(client, zara, lost_z["id"]) == "ACTIVE"


def test_closed_report_is_not_matched_by_a_queued_run(client):
    owner, finder, lost, found = _pair(client)
    assert client.put(f"/reports/{lost['id']}", headers=owner, json={"status": "CLOSED"}).status_code == 200

    # A background run queued before the close must not create suggestions for a closed report.
    process_report(lost["id"])

    assert _matches(client, finder, found["id"]) == []
    with SessionLocal() as db:
        assert db.scalars(select(MatchCandidate)).all() == []


def test_concurrent_runs_produce_one_suggestion_per_pair(client, monkeypatch):
    owner, finder, lost, found = _pair(client)
    # Widen the read-then-insert window so overlapping runs would collide without the lock.
    real_score = orchestrator.score_candidates

    def slow_score(*args, **kwargs):
        time.sleep(0.05)
        return real_score(*args, **kwargs)

    monkeypatch.setattr(orchestrator, "score_candidates", slow_score)
    with SessionLocal() as db:  # reset to the state just before the first run
        for m in db.scalars(select(MatchCandidate)).all():
            db.delete(m)
        for r in db.scalars(select(ItemReport)).all():
            r.status, r.ai_status = ReportStatus.ACTIVE, AIStatus.PENDING
        db.commit()

    threads = [threading.Thread(target=process_report, args=(rid,)) for rid in [lost["id"], found["id"]] * 4]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with SessionLocal() as db:
        rows = db.scalars(select(MatchCandidate)).all()
        assert len(rows) == 1
        statuses = {r.ai_status for r in db.scalars(select(ItemReport)).all()}
        assert statuses == {AIStatus.DONE}
