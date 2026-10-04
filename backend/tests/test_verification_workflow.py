"""Ownership verification: authorization, pass and fail, retry cap, notifications, privacy, audit and recovery.

Verification is tied to one match. AI matching is not proof of ownership. The finder compares the owner's answers
with the item, as the existing design requires. Nothing is shown to the finder before the owner submits.
"""

from app.ai.verification import MAX_VERIFICATION_ATTEMPTS
from app.db.session import SessionLocal
from app.models import AuditLog, ItemReport
from app.models.enums import ReportStatus
from tests.conftest import register
from tests.helpers import FOUND_BACKPACK, LOST_BACKPACK
from tests.test_reports_security import make_admin

SECRET = "blue calculus notebook and a green water bottle"  # the owner's private answer
EXTRA = "small tear inside the front pocket"
FORBIDDEN_IN_NOTIFICATIONS = ("finder@example.com", "owner@example.com", SECRET, EXTRA, "latitude", "longitude")


def _match(client, owner, lost):
    return client.get(f"/reports/{lost['id']}/matches", headers=owner).json()["matches"][0]


def _setup(client):
    owner = register(client, "Ayesha Khan", "owner@example.com")
    finder = register(client, "Bilal Ahmed", "finder@example.com")
    lost = client.post("/reports", json=LOST_BACKPACK, headers=owner).json()
    found = client.post("/reports", json=FOUND_BACKPACK, headers=finder).json()
    return {"owner": owner, "finder": finder, "lost": lost, "found": found, "match": _match(client, owner, lost)}


def _answer(client, ids, contents=SECRET):
    mid = ids["match"]["id"]
    assert client.post(f"/matches/{mid}/verification", headers=ids["owner"]).status_code == 201
    r = client.post(f"/matches/{mid}/verification/answers", headers=ids["owner"],
                    json={"answers": {"contents": contents, "hidden_feature": EXTRA}})
    assert r.status_code == 200, r.text


def _notes(client, headers):
    return client.get("/notifications", headers=headers).json()["notifications"]


def _audit(prefix):
    with SessionLocal() as db:
        return db.query(AuditLog).filter(AuditLog.action.like(f"{prefix}%")).all()


# ---- authorization --------------------------------------------------------------------------------------

def test_anonymous_and_unrelated_users_cannot_start_or_read_verification(client):
    ids = _setup(client)
    mid = ids["match"]["id"]
    stranger = register(client, "Stranger", "stranger@example.com")
    admin = make_admin(client)
    assert client.post(f"/matches/{mid}/verification").status_code == 401
    assert client.post(f"/matches/{mid}/verification", headers=stranger).status_code == 404
    assert client.get(f"/matches/{mid}/verification", headers=stranger).status_code == 404
    assert client.post(f"/matches/{mid}/verification", headers=ids["finder"]).status_code == 404  # finder cannot claim
    assert client.post(f"/matches/{mid}/verification", headers=admin).status_code == 404  # admin is not the owner


def test_finder_and_strangers_cannot_answer_or_decide(client):
    ids = _setup(client)
    mid = ids["match"]["id"]
    stranger = register(client, "Stranger", "stranger@example.com")
    _answer(client, ids)
    assert client.post(f"/matches/{mid}/verification/answers", headers=ids["finder"],
                       json={"answers": {"contents": "x"}}).status_code == 404
    assert client.post(f"/matches/{mid}/verification/answers", headers=stranger,
                       json={"answers": {"contents": "x"}}).status_code == 404
    assert client.post(f"/matches/{mid}/verify", headers=ids["owner"], json={"decision": "ACCEPT"}).status_code == 404
    assert client.post(f"/matches/{mid}/verify", headers=stranger, json={"decision": "ACCEPT"}).status_code == 404


def test_direct_api_calls_cannot_skip_the_steps(client):
    ids = _setup(client)
    mid = ids["match"]["id"]
    # answers before starting, and a decision before any answers, are both refused
    assert client.post(f"/matches/{mid}/verification/answers", headers=ids["owner"],
                       json={"answers": {"contents": SECRET}}).status_code == 409
    assert client.post(f"/matches/{mid}/verify", headers=ids["finder"], json={"decision": "ACCEPT"}).status_code == 409
    assert client.get(f"/reports/{ids['lost']['id']}/matches", headers=ids["owner"]).json()["matches"][0]["status"] \
        == "POTENTIAL_MATCH"


# ---- pass and fail ---------------------------------------------------------------------------------------

def test_correct_verification_connects_the_case_and_notifies_both_parties(client):
    ids = _setup(client)
    _answer(client, ids)
    r = client.post(f"/matches/{ids['match']['id']}/verify", headers=ids["finder"], json={"decision": "ACCEPT"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "VERIFIED" and r.json()["case_id"]
    owner_types = [n["type"] for n in _notes(client, ids["owner"])]
    finder_types = [n["type"] for n in _notes(client, ids["finder"])]
    assert "verification_accepted" in owner_types
    assert "case_connected" in finder_types


def test_failed_verification_is_safe_and_reveals_nothing(client):
    ids = _setup(client)
    _answer(client, ids, contents="a wrong guess")
    r = client.post(f"/matches/{ids['match']['id']}/verify", headers=ids["finder"], json={"decision": "REJECT"})
    assert r.json()["status"] == "REJECTED"
    owner_note = next(n for n in _notes(client, ids["owner"]) if n["type"] == "verification_rejected")
    assert "could not confirm ownership" in owner_note["message"]
    assert "wrong guess" not in owner_note["message"] and "contents" not in owner_note["message"]
    # the owner's view of their own verification shows status only, never advisory notes or the finder's view
    v = client.get(f"/matches/{ids['match']['id']}/verification", headers=ids["owner"]).json()
    assert v["status"] == "REJECTED"
    for forbidden in ("advisory_score", "advisory_notes", "answers_are_wrong"):
        assert forbidden not in v


def test_the_expected_answer_is_never_returned(client):
    ids = _setup(client)
    mid = ids["match"]["id"]
    start = client.post(f"/matches/{mid}/verification", headers=ids["owner"])
    assert start.status_code == 201
    for q in start.json()["questions"]:
        assert set(q) <= {"id", "question", "evidence_type", "optional"}  # no expected answer field
    client.post(f"/matches/{mid}/verification/answers", headers=ids["owner"],
                json={"answers": {"contents": SECRET, "hidden_feature": EXTRA}})
    owner_view = client.get(f"/matches/{mid}/verification", headers=ids["owner"]).json()
    assert "questions" in owner_view and "my_answers" in owner_view
    for q in owner_view["questions"]:
        assert set(q) <= {"id", "question", "evidence_type", "optional"}
    # the owner's own answers are visible to the owner; nobody else's are
    stranger = register(client, "Stranger", "stranger@example.com")
    assert client.get(f"/matches/{mid}/verification", headers=stranger).status_code == 404


def test_verification_is_tied_to_its_own_match(client):
    ids = _setup(client)
    other_finder = register(client, "Other Finder", "other-finder@example.com")
    other_found = client.post("/reports", json=dict(FOUND_BACKPACK, name="Second backpack"), headers=other_finder).json()
    _answer(client, ids)
    # the second found report belongs to a different match; a decision on it cannot use the first match's answers
    second_matches = client.get(f"/reports/{ids['lost']['id']}/matches", headers=ids["owner"]).json()["matches"]
    other_match = next(m for m in second_matches if m["other_report"]["id"] == other_found["id"])
    assert other_match["id"] != ids["match"]["id"]
    # the other match was never started, so it is not awaiting review and cannot be decided
    assert client.post(f"/matches/{other_match['id']}/verify", headers=other_finder,
                       json={"decision": "ACCEPT"}).status_code == 409


# ---- retry cap and invalid states ------------------------------------------------------------------------

def test_rejected_claim_can_be_retried_until_the_cap(client):
    ids = _setup(client)
    mid = ids["match"]["id"]
    for attempt in range(1, MAX_VERIFICATION_ATTEMPTS + 1):
        if attempt == 1:
            _answer(client, ids, contents="guess")  # the first attempt: start and submit
        else:
            assert client.post(f"/matches/{mid}/verification", headers=ids["owner"]).status_code == 201  # retry
            assert client.post(f"/matches/{mid}/verification/answers", headers=ids["owner"],
                               json={"answers": {"contents": "guess"}}).status_code == 200
        r = client.post(f"/matches/{mid}/verify", headers=ids["finder"], json={"decision": "REJECT"})
        assert r.status_code == 200, r.text
        left = client.get(f"/reports/{ids['lost']['id']}/matches", headers=ids["owner"]).json()["matches"][0][
            "verification_attempts_left"]
        assert left == MAX_VERIFICATION_ATTEMPTS - attempt
    # the cap is reached: no further attempt, and the owner is told so
    assert client.post(f"/matches/{mid}/verification", headers=ids["owner"]).status_code == 409


def test_verified_match_cannot_be_started_again(client):
    ids = _setup(client)
    _answer(client, ids)
    client.post(f"/matches/{ids['match']['id']}/verify", headers=ids["finder"], json={"decision": "ACCEPT"})
    assert client.post(f"/matches/{ids['match']['id']}/verification", headers=ids["owner"]).status_code == 409


def test_finder_sees_no_attempt_counter(client):
    ids = _setup(client)
    finder_view = client.get(f"/matches/{ids['match']['id']}", headers=ids["finder"]).json()
    assert finder_view["verification_attempts_left"] is None


# ---- notifications ---------------------------------------------------------------------------------------

def test_strong_match_notifies_owner_and_finder(client):
    ids = _setup(client)
    assert "match_owner" in [n["type"] for n in _notes(client, ids["owner"])]
    assert "match_finder" in [n["type"] for n in _notes(client, ids["finder"])]


def test_weak_match_creates_no_notification(client):
    owner = register(client, "Ayesha Khan", "owner@example.com")
    finder = register(client, "Bilal Ahmed", "finder@example.com")
    lost = client.post("/reports", json=dict(LOST_BACKPACK, distinctive_features="Red keychain on the front zipper"),
                       headers=owner).json()
    client.post("/reports", json=dict(FOUND_BACKPACK, distinctive_features="Has a red keychain attached to the zipper"),
                headers=finder)
    match = _match(client, owner, lost)
    assert match["lead"] == "WEAK"
    assert "match_owner" not in [n["type"] for n in _notes(client, owner)]
    assert "match_finder" not in [n["type"] for n in _notes(client, finder)]


def test_notifications_go_only_to_the_intended_party(client):
    ids = _setup(client)
    _answer(client, ids)
    stranger = register(client, "Stranger", "stranger@example.com")
    assert "verification_submitted" in [n["type"] for n in _notes(client, ids["finder"])]
    assert "verification_submitted" not in [n["type"] for n in _notes(client, ids["owner"])]
    assert _notes(client, stranger) == []


def test_notification_payloads_contain_no_private_information(client):
    ids = _setup(client)
    _answer(client, ids)
    client.post(f"/matches/{ids['match']['id']}/verify", headers=ids["finder"], json={"decision": "ACCEPT"})
    text = str(_notes(client, ids["owner"])) + str(_notes(client, ids["finder"]))
    for leaked in FORBIDDEN_IN_NOTIFICATIONS:
        assert leaked not in text, leaked


def test_recovery_notifies_the_other_party(client):
    ids = _setup(client)
    _answer(client, ids)
    case_id = client.post(f"/matches/{ids['match']['id']}/verify", headers=ids["finder"],
                          json={"decision": "ACCEPT"}).json()["case_id"]
    client.put(f"/cases/{case_id}/status", headers=ids["owner"], json={"status": "RECOVERED"})
    assert "case_recovered" in [n["type"] for n in _notes(client, ids["finder"])]


# ---- recovery lifecycle, archiving and audit ------------------------------------------------------------

def test_recovered_items_are_archived_removed_from_listings_and_kept(client):
    ids = _setup(client)
    _answer(client, ids)
    case_id = client.post(f"/matches/{ids['match']['id']}/verify", headers=ids["finder"],
                          json={"decision": "ACCEPT"}).json()["case_id"]
    client.put(f"/cases/{case_id}/status", headers=ids["owner"], json={"status": "RECOVERED"})
    listed = [x["id"] for x in client.get("/reports", headers=ids["finder"]).json()["items"]]
    assert ids["lost"]["id"] not in listed and ids["found"]["id"] not in listed
    with SessionLocal() as db:
        lost, found = db.get(ItemReport, ids["lost"]["id"]), db.get(ItemReport, ids["found"]["id"])
        assert lost.status == ReportStatus.RECOVERED and lost.archived_at is not None  # kept, not deleted
        assert found.archived_at is not None
    assert client.get(f"/reports/{ids['lost']['id']}", headers=ids["owner"]).json()["status"] == "RECOVERED"


def test_unrelated_user_cannot_change_a_case(client):
    ids = _setup(client)
    _answer(client, ids)
    case_id = client.post(f"/matches/{ids['match']['id']}/verify", headers=ids["finder"],
                          json={"decision": "ACCEPT"}).json()["case_id"]
    stranger = register(client, "Stranger", "stranger@example.com")
    assert client.put(f"/cases/{case_id}/status", headers=stranger, json={"status": "RECOVERED"}).status_code == 404
    assert client.get(f"/cases/{case_id}", headers=stranger).status_code == 404


def test_verification_steps_are_audited_without_answers(client):
    ids = _setup(client)
    _answer(client, ids)
    client.post(f"/matches/{ids['match']['id']}/verify", headers=ids["finder"], json={"decision": "ACCEPT"})
    actions = {a.action for a in _audit("verification")}
    assert {"verification.started", "verification.submitted", "verification.accepted"} <= actions
    for entry in _audit("verification"):
        assert SECRET not in str(entry.meta) and EXTRA not in str(entry.meta)
