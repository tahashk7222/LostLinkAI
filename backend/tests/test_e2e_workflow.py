"""End-to-end demo scenario: lost backpack -> found backpack -> match -> verify -> chat -> recovered."""

from tests.conftest import register
from tests.helpers import FOUND_BACKPACK, FOUND_UNRELATED, LOST_BACKPACK, make_image


def upload(client, headers, report_id, data):
    r = client.post(f"/reports/{report_id}/images", headers=headers,
                    files={"file": ("photo.jpg", data, "image/jpeg")})
    assert r.status_code == 201, r.text
    return r.json()


def test_full_recovery_workflow(client):
    # 1-2. Owner reports a lost backpack with a photo
    owner = register(client, "Ayesha Khan", "owner@example.com")
    lost = client.post("/reports", json=LOST_BACKPACK, headers=owner).json()
    upload(client, owner, lost["id"], make_image())

    # 3-4. Finder reports a found backpack with a photo (plus an unrelated item from someone else)
    finder = register(client, "Bilal Ahmed", "finder@example.com")
    other = register(client, "Other", "other@example.com")
    client.post("/reports", json=FOUND_UNRELATED, headers=other)
    found = client.post("/reports", json=FOUND_BACKPACK, headers=finder).json()
    upload(client, finder, found["id"], make_image(color=(25, 25, 25)))

    # 5-6. Matching ran automatically; the owner sees a ranked potential match with explanation
    r = client.get(f"/reports/{lost['id']}/matches", headers=owner).json()
    assert r["ai_status"] == "DONE"
    assert len(r["matches"]) == 1, r
    match = r["matches"][0]
    assert match["other_report"]["id"] == found["id"]
    assert match["score_percent"] >= 55
    assert any("Same item category" in e for e in match["explanation"])
    assert "not proof of ownership" in match["disclaimer"]
    # The owner must not see the finder's private details or exact coordinates
    assert "private_details" not in match["other_report"]
    assert "latitude" not in match["other_report"]

    # Explicit re-run is idempotent (no duplicate matches)
    rerun = client.post(f"/reports/{lost['id']}/match", headers=owner).json()
    assert [m["id"] for m in rerun["matches"]] == [match["id"]]

    # 7. Owner was notified, without private info
    notes = client.get("/notifications", headers=owner).json()
    owner_note = next(n for n in notes["notifications"] if n["type"] == "match_owner")
    assert "LostLink AI found a potential match for your lost item" in owner_note["message"]
    assert "finder@example.com" not in owner_note["message"]
    assert client.post(f"/notifications/{owner_note['id']}/read", headers=owner).json()["read"] is True

    # No chat before verification
    assert client.get("/cases", headers=owner).json()["cases"] == []

    # 8. Owner starts verification and answers private questions
    v = client.post(f"/matches/{match['id']}/verification", headers=owner)
    assert v.status_code == 201, v.text
    questions = v.json()["questions"]
    assert any(q["id"] == "contents" for q in questions)
    # Finder cannot answer on the owner's behalf
    assert client.post(f"/matches/{match['id']}/verification/answers", headers=finder,
                       json={"answers": {"contents": "x"}}).status_code == 404
    r = client.post(f"/matches/{match['id']}/verification/answers", headers=owner, json={"answers": {
        "contents": "A blue calculus notebook, my Casio calculator and a green water bottle",
        "hidden_feature": "Small tear inside the front pocket"}})
    assert r.status_code == 200, r.text
    assert r.json()["match_status"] == "AWAITING_FINDER_REVIEW"

    # Owner cannot approve their own claim
    assert client.post(f"/matches/{match['id']}/verify", headers=owner, json={"decision": "ACCEPT"}).status_code == 404

    # 9. Finder reviews answers + advisory score and accepts
    fv = client.get(f"/matches/{match['id']}/verification", headers=finder).json()
    assert fv["answers"]["contents"].startswith("A blue calculus notebook")
    assert 0 <= fv["advisory_score"] <= 1
    assert any("advisory" in n for n in fv["advisory_notes"])
    r = client.post(f"/matches/{match['id']}/verify", headers=finder, json={"decision": "ACCEPT"})
    assert r.status_code == 200, r.text
    case_id = r.json()["case_id"]
    assert r.json()["status"] == "VERIFIED"

    # 10. Controlled communication (no emails exposed)
    case = client.get(f"/cases/{case_id}", headers=owner).json()
    assert case["status"] == "CONNECTED"
    assert case["finder_name"] == "Bilal"
    assert "finder@example.com" not in str(case)
    client.post(f"/cases/{case_id}/messages", headers=owner, json={"message": "Thank you! Can we meet at the library desk?"})
    client.post(f"/cases/{case_id}/messages", headers=finder, json={"message": "Sure, 5 PM today."})
    msgs = client.get(f"/cases/{case_id}/messages", headers=finder).json()["messages"]
    assert [m["mine"] for m in msgs] == [False, True]
    assert msgs[0]["sender_name"] == "Ayesha"
    # Outsider cannot read the conversation
    assert client.get(f"/cases/{case_id}/messages", headers=other).status_code == 404

    # 11. Mark recovered
    r = client.put(f"/cases/{case_id}/status", headers=owner, json={"status": "RECOVERED"})
    assert r.status_code == 200
    assert client.get(f"/reports/{lost['id']}", headers=owner).json()["status"] == "RECOVERED"
    assert client.get(f"/reports/{found['id']}", headers=finder).json()["status"] == "RECOVERED"
    assert any(n["type"] == "case_recovered" for n in client.get("/notifications", headers=finder).json()["notifications"])
    # Recovered cannot go back to connected
    assert client.put(f"/cases/{case_id}/status", headers=owner, json={"status": "CONNECTED"}).status_code == 409


def test_rejected_verification_reopens_reports(client):
    owner = register(client, "Owner", "o@example.com")
    finder = register(client, "Finder", "f@example.com")
    lost = client.post("/reports", json=LOST_BACKPACK, headers=owner).json()
    client.post("/reports", json=FOUND_BACKPACK, headers=finder)
    match = client.get(f"/reports/{lost['id']}/matches", headers=owner).json()["matches"][0]
    client.post(f"/matches/{match['id']}/verification", headers=owner)
    client.post(f"/matches/{match['id']}/verification/answers", headers=owner, json={"answers": {"contents": "no idea"}})
    r = client.post(f"/matches/{match['id']}/verify", headers=finder, json={"decision": "REJECT"})
    assert r.json()["status"] == "REJECTED"
    assert client.get(f"/reports/{lost['id']}", headers=owner).json()["status"] == "ACTIVE"
    assert client.get("/cases", headers=owner).json()["cases"] == []
    # cannot restart a rejected match
    assert client.post(f"/matches/{match['id']}/verification", headers=owner).status_code == 409
