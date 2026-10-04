"""Finder possession confirmation after owner verification.

This is NOT ownership verification. The owner's verification (and the finder's ownership decision, which is unchanged)
comes first. The finder then only says whether they still have the item. The owner's answers, the advisory score and
the advisory notes never reach the finder.
"""

from app.db.session import SessionLocal
from app.models import AuditLog, Case, ItemReport
from app.models.enums import CaseStatus, ReportStatus
from tests.test_verification_workflow import EXTRA, SECRET, _answer, _setup


def _verified_case(client):
    ids = _setup(client)
    _answer(client, ids)
    case_id = client.post(f"/matches/{ids['match']['id']}/verify", headers=ids["finder"],
                          json={"decision": "ACCEPT"}).json()["case_id"]
    ids["case"] = case_id
    return ids


def _notes(client, headers):
    return client.get("/notifications", headers=headers).json()["notifications"]


def _audit(prefix):
    with SessionLocal() as db:
        return db.query(AuditLog).filter(AuditLog.action.like(f"{prefix}%")).all()


# 1-2. Owner verification succeeds and the finder sees a safe 'passed' status
def test_finder_sees_verification_passed_and_no_private_material(client):
    ids = _verified_case(client)
    view = client.get(f"/matches/{ids['match']['id']}/verification", headers=ids["finder"]).json()
    assert view["match_status"] == "VERIFIED"
    assert "answers" not in view and "advisory_score" not in view and "advisory_notes" not in view
    case = client.get(f"/cases/{ids['case']}", headers=ids["finder"]).json()
    assert case["status"] == "CONNECTED" and case["possession_confirmed_at"] is None
    assert SECRET not in str(case) and EXTRA not in str(case)


# 3-5. Finder confirms possession; nothing private is exposed; the owner is told to arrange the handover
def test_finder_confirms_possession(client):
    ids = _verified_case(client)
    r = client.post(f"/cases/{ids['case']}/possession", headers=ids["finder"], json={"still_have": True})
    assert r.status_code == 200, r.text
    assert r.json()["possession_confirmed_at"] is not None
    assert r.json()["status"] == "CONNECTED"  # the existing recovery workflow continues from here
    assert "possession_confirmed" in [n["type"] for n in _notes(client, ids["owner"])]
    assert any(a.entity_id == ids["case"] for a in _audit("case.possession_confirmed"))


# 6. Finder rejects recovery through the existing close lifecycle, and the reports return to active listings
def test_finder_no_longer_has_item_closes_the_case_through_the_existing_lifecycle(client):
    ids = _verified_case(client)
    r = client.post(f"/cases/{ids['case']}/possession", headers=ids["finder"], json={"still_have": False})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "CLOSED"
    with SessionLocal() as db:
        assert db.get(ItemReport, ids["lost"]["id"]).status == ReportStatus.ACTIVE
        assert db.get(ItemReport, ids["found"]["id"]).status == ReportStatus.ACTIVE
        assert db.get(Case, ids["case"]).status == CaseStatus.CLOSED
    assert "case_closed" in [n["type"] for n in _notes(client, ids["owner"])]
    assert any(a.entity_id == ids["case"] for a in _audit("case.possession_declined"))


# 7-8. Unrelated users and the owner cannot make the finder's statement; the admin cannot either
def test_only_the_finder_can_confirm_possession(client):
    from tests.conftest import register
    from tests.test_reports_security import make_admin
    ids = _verified_case(client)
    stranger = register(client, "Stranger", "stranger@example.com")
    admin = make_admin(client)
    for headers in (ids["owner"], stranger, admin):
        assert client.post(f"/cases/{ids['case']}/possession", headers=headers,
                           json={"still_have": True}).status_code == 404
    assert client.post(f"/cases/{ids['case']}/possession", json={"still_have": True}).status_code == 401
    with SessionLocal() as db:
        assert db.get(Case, ids["case"]).possession_confirmed_at is None


# 9. Case transitions stay valid
def test_possession_is_a_one_time_statement_on_a_connected_case(client):
    ids = _verified_case(client)
    assert client.post(f"/cases/{ids['case']}/possession", headers=ids["finder"],
                       json={"still_have": True}).status_code == 200
    assert client.post(f"/cases/{ids['case']}/possession", headers=ids["finder"],
                       json={"still_have": True}).status_code == 409  # already confirmed


def test_closed_case_cannot_take_a_possession_statement(client):
    ids = _verified_case(client)
    client.post(f"/cases/{ids['case']}/possession", headers=ids["finder"], json={"still_have": False})
    assert client.post(f"/cases/{ids['case']}/possession", headers=ids["finder"],
                       json={"still_have": True}).status_code == 409


def test_recovery_still_works_after_possession_is_confirmed(client):
    ids = _verified_case(client)
    client.post(f"/cases/{ids['case']}/possession", headers=ids["finder"], json={"still_have": True})
    r = client.put(f"/cases/{ids['case']}/status", headers=ids["owner"], json={"status": "RECOVERED"})
    assert r.status_code == 200, r.text
    assert client.get(f"/reports/{ids['lost']['id']}", headers=ids["owner"]).json()["status"] == "RECOVERED"


# 10-11. Notifications and audit entries stay privacy-safe
def test_possession_notifications_and_audit_contain_no_private_information(client):
    ids = _verified_case(client)
    client.post(f"/cases/{ids['case']}/possession", headers=ids["finder"], json={"still_have": True})
    for headers in (ids["owner"], ids["finder"]):
        text = str(_notes(client, headers))
        assert SECRET not in text and EXTRA not in text and "finder@example.com" not in text
    for entry in _audit("case."):
        assert SECRET not in str(entry.meta) and EXTRA not in str(entry.meta)
