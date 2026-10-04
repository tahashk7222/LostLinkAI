"""Admin portal: authorization, moderation, lifecycle (recovered and archived), monitoring and privacy."""

from app.ai.config import get_matching_config
from app.ai.retrieval import retrieve_candidates
from app.db.session import SessionLocal
from app.models import AuditLog, ItemReport, Verification
from app.models.enums import ModerationReason, ReportStatus
from tests.conftest import register
from tests.helpers import FOUND_BACKPACK, LOST_BACKPACK
from tests.test_reports_security import make_admin

PRIVATE_ANSWER = "A blue calculus notebook and a green water bottle"  # the owner's secret; must never reach admins


def _audit(actions_prefix: str) -> list[AuditLog]:
    with SessionLocal() as db:
        return db.query(AuditLog).filter(AuditLog.action.like(f"{actions_prefix}%")).all()


def _recovered_case(client):
    """Lost and found backpacks, a verified match, a case, then recovered. Returns the ids and headers."""
    owner = register(client, "Ayesha Khan", "owner@example.com")
    finder = register(client, "Bilal Ahmed", "finder@example.com")
    lost = client.post("/reports", json=LOST_BACKPACK, headers=owner).json()
    found = client.post("/reports", json=FOUND_BACKPACK, headers=finder).json()
    m = client.get(f"/reports/{lost['id']}/matches", headers=owner).json()["matches"][0]
    assert client.post(f"/matches/{m['id']}/verification", headers=owner).status_code == 201
    client.post(f"/matches/{m['id']}/verification/answers", headers=owner,
                json={"answers": {"contents": PRIVATE_ANSWER, "hidden_feature": "Small tear inside the front pocket"}})
    case_id = client.post(f"/matches/{m['id']}/verify", headers=finder, json={"decision": "ACCEPT"}).json()["case_id"]
    return {"owner": owner, "finder": finder, "lost": lost, "found": found, "match": m, "case": case_id}


def _recover(client, ids):
    r = client.put(f"/cases/{ids['case']}/status", headers=ids["owner"], json={"status": "RECOVERED"})
    assert r.status_code == 200, r.text


# 1. Authorization: non-admin and anonymous callers are refused on every new admin endpoint
def test_non_admin_and_anonymous_are_refused(client):
    ids = _recovered_case(client)
    user = ids["owner"]
    paths = [("GET", "/admin/dashboard"), ("GET", f"/admin/reports/{ids['lost']['id']}"),
             ("POST", f"/admin/reports/{ids['lost']['id']}/approve"),
             ("POST", f"/admin/reports/{ids['lost']['id']}/reject"),
             ("GET", "/admin/verification"), ("GET", f"/admin/cases/{ids['case']}"),
             ("POST", f"/admin/cases/{ids['case']}/close")]
    for method, path in paths:
        assert client.request(method, path, headers=user, json={"reason": "OTHER"}).status_code == 403, path
        assert client.request(method, path, json={"reason": "OTHER"}).status_code == 401, path


# 2. Dashboard uses real data
def test_admin_dashboard_counts_real_reports(client):
    admin = make_admin(client)
    owner = register(client, "Ayesha Khan", "owner@example.com")
    client.post("/reports", json=LOST_BACKPACK, headers=owner)
    d = client.get("/admin/dashboard", headers=admin)
    assert d.status_code == 200, d.text
    body = d.json()
    assert body["cards"]["active_lost"] == 1
    assert body["cards"]["active_found"] == 0
    assert body["recent_reports"][0]["name"] == LOST_BACKPACK["name"]
    assert "recent_matches" in body and "recent_actions" in body


# 3. Approve keeps the report live and is audited
def test_admin_approves_report_and_audit_records_it(client):
    admin = make_admin(client)
    owner = register(client, "Ayesha Khan", "owner@example.com")
    lost = client.post("/reports", json=LOST_BACKPACK, headers=owner).json()
    r = client.post(f"/admin/reports/{lost['id']}/approve", headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ACTIVE"
    entries = [a for a in _audit("admin.report_approved") if a.entity_id == lost["id"]]
    assert entries and entries[0].actor_id is not None


# 4. Reject stores the reason and note, notifies the owner, and audits only the reason code
def test_admin_rejects_report_with_reason_and_audits_the_code_only(client):
    admin = make_admin(client)
    owner = register(client, "Ayesha Khan", "owner@example.com")
    lost = client.post("/reports", json=LOST_BACKPACK, headers=owner).json()
    note = "Reported location is outside the supported service area."
    r = client.post(f"/admin/reports/{lost['id']}/reject", headers=admin,
                    json={"reason": ModerationReason.OUTSIDE_UET_AREA.value, "note": note})
    assert r.status_code == 200, r.text
    detail = client.get(f"/admin/reports/{lost['id']}", headers=admin).json()
    assert detail["status"] == "DEACTIVATED"
    assert detail["moderation"]["reason"] == "OUTSIDE_UET_AREA"
    assert detail["moderation"]["note"] == note
    entries = [a for a in _audit("admin.report_rejected") if a.entity_id == lost["id"]]
    assert entries and entries[0].meta["reason"] == "OUTSIDE_UET_AREA"
    assert note not in str(entries[0].meta)  # the free-text note is not copied into the audit log
    assert any(n["type"] == "report_deactivated" for n in client.get("/notifications", headers=owner).json()["notifications"])


def test_reject_needs_a_valid_reason(client):
    admin = make_admin(client)
    owner = register(client, "Ayesha Khan", "owner@example.com")
    lost = client.post("/reports", json=LOST_BACKPACK, headers=owner).json()
    assert client.post(f"/admin/reports/{lost['id']}/reject", headers=admin,
                       json={"reason": "BECAUSE"}).status_code == 422


# 5. A rejected report does not take part in normal matching
def test_rejected_report_is_not_matched(client):
    admin = make_admin(client)
    owner = register(client, "Ayesha Khan", "owner@example.com")
    finder = register(client, "Bilal Ahmed", "finder@example.com")
    found = client.post("/reports", json=FOUND_BACKPACK, headers=finder).json()
    assert client.post(f"/admin/reports/{found['id']}/reject", headers=admin,
                       json={"reason": "FAKE_OR_JOKE"}).status_code == 200
    lost = client.post("/reports", json=LOST_BACKPACK, headers=owner).json()
    assert client.get(f"/reports/{lost['id']}/matches", headers=owner).json()["matches"] == []
    with SessionLocal() as db:
        rejected = db.get(ItemReport, found["id"])
        assert rejected.status == ReportStatus.DEACTIVATED
        candidates = retrieve_candidates(db, db.get(ItemReport, lost["id"]), get_matching_config())
        assert found["id"] not in [c.id for c in candidates]


# 6. A report in a recovery case cannot be rejected through moderation
def test_report_in_a_case_cannot_be_rejected(client):
    admin = make_admin(client)
    ids = _recovered_case(client)
    r = client.post(f"/admin/reports/{ids['lost']['id']}/reject", headers=admin, json={"reason": "OTHER"})
    assert r.status_code == 409


# 7 and 8. A recovered item leaves active listings and matching; the record is archived and kept
def test_recovered_item_is_inactive_archived_and_kept(client):
    admin = make_admin(client)
    ids = _recovered_case(client)
    _recover(client, ids)
    public = client.get("/reports", headers=ids["finder"]).json()["items"]  # another user's view of listings
    assert ids["lost"]["id"] not in [x["id"] for x in public]
    assert ids["found"]["id"] not in [x["id"] for x in public]
    detail = client.get(f"/admin/reports/{ids['lost']['id']}", headers=admin).json()
    assert detail["status"] == "RECOVERED"
    assert detail["archived_at"] is not None  # archived, not deleted
    assert any(a.entity_id == ids["lost"]["id"] for a in _audit("item.archived"))


# 9 and 10. Admin close and the recovery confirmation view
def test_admin_sees_recovery_confirmation_and_can_close_the_case(client):
    admin = make_admin(client)
    ids = _recovered_case(client)
    _recover(client, ids)
    c = client.get(f"/admin/cases/{ids['case']}", headers=admin).json()
    assert c["status"] == "RECOVERED" and c["recovery_confirmed"] is True
    assert c["lost"]["active_listing"] is False and c["lost"]["matching_eligible"] is False
    assert c["lost"]["archived"] is True
    assert c["verification_status"] == "verified"
    r = client.post(f"/admin/cases/{ids['case']}/close", headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "CLOSED"
    assert any(a.entity_id == ids["case"] for a in _audit("admin.case_closed"))
    assert client.get(f"/admin/reports/{ids['lost']['id']}", headers=admin).json()["status"] == "CLOSED"


# 11. Verification monitoring never exposes secrets
def test_verification_monitor_has_no_secret_answers(client):
    admin = make_admin(client)
    _recovered_case(client)
    body = client.get("/admin/verification", headers=admin).json()
    assert body["verifications"] and body["verifications"][0]["display_status"] == "verified"
    text = str(body)
    assert PRIVATE_ANSWER not in text and "hidden_feature" not in text and "tear inside" not in text
    for forbidden in ("answers", "questions", "advisory_score", "advisory_notes"):
        assert forbidden not in body["verifications"][0]


# 12. Report detail omits private details, exact coordinates and the reporter's full email
def test_admin_report_detail_is_minimal(client):
    admin = make_admin(client)
    owner = register(client, "Ayesha Khan", "owner@example.com")
    lost = client.post("/reports", json=LOST_BACKPACK, headers=owner).json()
    d = client.get(f"/admin/reports/{lost['id']}", headers=admin).json()
    text = str(d)
    assert LOST_BACKPACK["private_details"] not in text
    assert "latitude" not in d and "longitude" not in d
    assert "owner@example.com" not in text and d["reporter_email"].startswith("o***")


# 13. A Weak match cannot be turned into verification through admin routes or as the owner
def test_weak_match_cannot_start_verification_through_admin_routes(client):
    admin = make_admin(client)
    owner = register(client, "Ayesha Khan", "owner@example.com")
    finder = register(client, "Bilal Ahmed", "finder@example.com")
    weak_lost = dict(LOST_BACKPACK, distinctive_features="Red keychain on the front zipper")
    weak_found = dict(FOUND_BACKPACK, distinctive_features="Has a red keychain attached to the zipper")
    lost = client.post("/reports", json=weak_lost, headers=owner).json()
    client.post("/reports", json=weak_found, headers=finder)
    match = client.get(f"/reports/{lost['id']}/matches", headers=owner).json()["matches"][0]
    assert match["lead"] == "WEAK"
    assert client.post(f"/matches/{match['id']}/verification", headers=owner).status_code == 409
    assert client.post(f"/matches/{match['id']}/verification", headers=admin).status_code == 404


# 14. Approve is only for open reports; a rejected report cannot be approved afterwards
def test_approve_refused_for_closed_report(client):
    admin = make_admin(client)
    owner = register(client, "Ayesha Khan", "owner@example.com")
    lost = client.post("/reports", json=LOST_BACKPACK, headers=owner).json()
    client.post(f"/admin/reports/{lost['id']}/reject", headers=admin, json={"reason": "OTHER"})
    assert client.post(f"/admin/reports/{lost['id']}/approve", headers=admin).status_code == 409


def test_verification_rows_exist_for_the_recovered_case(client):
    _recovered_case(client)
    with SessionLocal() as db:
        assert db.query(Verification).count() == 1
