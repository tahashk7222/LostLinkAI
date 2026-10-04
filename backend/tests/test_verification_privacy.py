"""Regression tests: the owner's verification answers never reach anyone but the owner.

Each test scans real API responses for the owner's secret text. The owner's own verification endpoint is the only
place the text may appear, and only for the owner.
"""

from tests.conftest import register
from tests.test_reports_security import make_admin
from tests.test_verification_workflow import EXTRA, SECRET, _answer, _match, _setup

SECRET_TEXTS = (SECRET, EXTRA)


def _submit_and_accept(client, ids):
    """Submit the owner's answers, then have the finder confirm. Returns the case id."""
    _answer(client, ids)
    return client.post(f"/matches/{ids['match']['id']}/verify", headers=ids["finder"],
                       json={"decision": "ACCEPT"}).json()["case_id"]


def _assert_no_secret(body, where: str):
    text = str(body)
    for secret in SECRET_TEXTS:
        assert secret not in text, f"{secret!r} leaked through {where}"


def test_owner_can_submit_and_sees_only_their_own_answers(client):
    ids = _setup(client)
    _answer(client, ids)
    mine = client.get(f"/matches/{ids['match']['id']}/verification", headers=ids["owner"]).json()
    assert mine["my_answers"]["contents"] == SECRET  # the owner sees their own submission
    assert "advisory_score" not in mine and "advisory_notes" not in mine


def test_finder_cannot_retrieve_the_submitted_answer(client):
    ids = _setup(client)
    _answer(client, ids)
    finder_view = client.get(f"/matches/{ids['match']['id']}/verification", headers=ids["finder"]).json()
    assert finder_view["match_status"] == "AWAITING_FINDER_REVIEW"  # the finder knows a decision is due
    assert set(finder_view) <= {"status", "match_status", "questions", "submitted_at", "decided_at"}
    _assert_no_secret(finder_view, "finder verification view")


def test_finder_still_decides_without_seeing_the_answers(client):
    ids = _setup(client)
    _answer(client, ids)
    r = client.post(f"/matches/{ids['match']['id']}/verify", headers=ids["finder"], json={"decision": "REJECT"})
    assert r.status_code == 200 and r.json()["status"] == "REJECTED"
    _assert_no_secret(r.json(), "finder decision response")


def test_unrelated_user_cannot_retrieve_the_answer(client):
    ids = _setup(client)
    _answer(client, ids)
    stranger = register(client, "Stranger", "stranger@example.com")
    for path in (f"/matches/{ids['match']['id']}/verification", f"/matches/{ids['match']['id']}"):
        r = client.get(path, headers=stranger)
        assert r.status_code == 404
        _assert_no_secret(r.json(), f"unrelated user {path}")


def test_admin_cannot_retrieve_the_answer_through_admin_endpoints(client):
    ids = _setup(client)
    case_id = _submit_and_accept(client, ids)
    client.put(f"/cases/{case_id}/status", headers=ids["owner"], json={"status": "RECOVERED"})
    admin = make_admin(client)
    mid = ids["match"]["id"]
    endpoints = ["/admin/dashboard", "/admin/verification", "/admin/matches", "/admin/cases", f"/admin/cases/{case_id}",
                 "/admin/audit", f"/admin/reports/{ids['lost']['id']}", f"/admin/reports/{ids['found']['id']}",
                 f"/matches/{mid}", f"/admin/reports?q=backpack"]
    for path in endpoints:
        r = client.get(path, headers=admin)
        assert r.status_code == 200, (path, r.status_code)
        _assert_no_secret(r.json(), f"admin {path}")
    # the admin's verification view shows status, never answers or advisory fields
    verifications = client.get("/admin/verification", headers=admin).json()["verifications"]
    assert verifications and all("answers" not in v and "advisory_score" not in v for v in verifications)


def test_lists_and_summaries_never_carry_the_answer(client):
    ids = _setup(client)
    _answer(client, ids)
    for headers in (ids["owner"], ids["finder"]):
        _assert_no_secret(client.get("/matches", headers=headers).json(), "match list")
        _assert_no_secret(client.get(f"/matches/{ids['match']['id']}", headers=headers).json(), "match summary")
        _assert_no_secret(client.get(f"/reports/{ids['lost']['id']}/matches", headers=headers).json(), "report matches")
        _assert_no_secret(client.get(f"/reports/{ids['found']['id']}/matches", headers=headers).json(), "found matches")
        _assert_no_secret(client.get("/reports", headers=headers).json(), "report list")


def test_case_responses_never_carry_the_answer(client):
    ids = _setup(client)
    case_id = _submit_and_accept(client, ids)
    for headers in (ids["owner"], ids["finder"]):
        _assert_no_secret(client.get("/cases", headers=headers).json(), "case list")
        _assert_no_secret(client.get(f"/cases/{case_id}", headers=headers).json(), "case detail")
        _assert_no_secret(client.get(f"/cases/{case_id}/messages", headers=headers).json(), "case messages")


def test_notifications_never_carry_the_answer(client):
    ids = _setup(client)
    _submit_and_accept(client, ids)
    for headers in (ids["owner"], ids["finder"]):
        _assert_no_secret(client.get("/notifications", headers=headers).json(), "notifications")


def test_owner_can_read_their_own_answer_but_others_cannot(client):
    ids = _setup(client)
    _answer(client, ids)
    assert client.get(f"/matches/{ids['match']['id']}/verification", headers=ids["owner"]).json()["my_answers"]
    finder_view = client.get(f"/matches/{ids['match']['id']}/verification", headers=ids["finder"]).json()
    assert "my_answers" not in finder_view


def test_match_summary_for_owner_exposes_no_answer_field(client):
    ids = _setup(client)
    _answer(client, ids)
    summary = _match(client, ids["owner"], ids["lost"])
    assert "answers" not in summary and "advisory_score" not in summary
    finder_summary = client.get(f"/matches/{ids['match']['id']}", headers=ids["finder"])
    assert finder_summary.status_code == 200  # the finder still sees the match itself
    assert "answers" not in finder_summary.json()
