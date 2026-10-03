from app.core.security import create_image_token
from app.db.session import SessionLocal
from app.models import User
from app.models.enums import Role
from tests.conftest import register
from tests.helpers import LOST_BACKPACK, make_image


def make_admin(client):
    headers = register(client, "Admin", "admin@example.com")
    with SessionLocal() as db:
        u = db.query(User).filter_by(email="admin@example.com").one()
        u.role = Role.ADMIN
        db.commit()
    return headers


def test_create_and_list_reports(client):
    a = register(client)
    r = client.post("/reports", json=LOST_BACKPACK, headers=a)
    assert r.status_code == 201
    body = r.json()
    assert body["is_owner"] and body["private_details"]  # owner sees own private details
    body = client.get(f"/reports/{body['id']}", headers=a).json()  # background analysis has run
    assert body["ai_status"] == "DONE"
    assert any(x["source"] == "USER" for x in body["attributes"])

    mine = client.get("/reports?mine=true", headers=a).json()
    assert mine["total"] == 1
    search = client.get("/reports?q=library&report_type=LOST", headers=a).json()
    assert search["total"] == 1


def test_missing_fields_rejected(client):
    a = register(client)
    no_location = {k: v for k, v in LOST_BACKPACK.items() if k not in ("location", "place_key")}
    assert client.post("/reports", json=no_location, headers=a).status_code == 422
    no_description = {k: v for k, v in LOST_BACKPACK.items() if k != "description"}
    assert client.post("/reports", json=no_description, headers=a).status_code == 422
    # The label is optional: it is filled in from the chosen place
    no_label = {k: v for k, v in LOST_BACKPACK.items() if k != "location"}
    assert client.post("/reports", json=no_label, headers=a).json()["location"] == "Lecture Theatre"


def test_other_user_sees_public_view_only(client):
    a = register(client)
    b = register(client, "Bob", "bob@example.com")
    rid = client.post("/reports", json=LOST_BACKPACK, headers=a).json()["id"]
    view = client.get(f"/reports/{rid}", headers=b).json()
    assert "private_details" not in view
    # No coordinates of any precision for other users; only label + zone
    assert not any(k in view for k in ("latitude", "longitude", "approx_latitude", "approx_longitude"))
    assert view["location"] == "Outside the Lecture Theatre" and view["zone"] == "campus"
    assert "email" not in str(view)
    assert view["reporter_name"] == "Alice"


def test_cannot_edit_or_delete_others_report(client):
    a = register(client)
    b = register(client, "Bob", "bob@example.com")
    rid = client.post("/reports", json=LOST_BACKPACK, headers=a).json()["id"]
    assert client.put(f"/reports/{rid}", json={"name": "hacked"}, headers=b).status_code == 403
    assert client.delete(f"/reports/{rid}", headers=b).status_code == 403
    assert client.post(f"/reports/{rid}/images", headers=b,
                       files={"file": ("x.jpg", make_image(), "image/jpeg")}).status_code == 403
    assert client.get(f"/reports/{rid}/matches", headers=b).status_code == 403


def test_edit_and_close_report(client):
    a = register(client)
    rid = client.post("/reports", json=LOST_BACKPACK, headers=a).json()["id"]
    r = client.put(f"/reports/{rid}", json={"color": "Dark grey"}, headers=a)
    assert r.json()["color"] == "Dark grey"
    assert client.put(f"/reports/{rid}", json={"status": "RECOVERED"}, headers=a).status_code == 400
    assert client.put(f"/reports/{rid}", json={"status": "CLOSED"}, headers=a).json()["status"] == "CLOSED"
    assert client.put(f"/reports/{rid}", json={"color": "red"}, headers=a).status_code == 409


def test_image_upload_validation(client):
    a = register(client)
    rid = client.post("/reports", json=LOST_BACKPACK, headers=a).json()["id"]
    up = lambda name, data, ct: client.post(f"/reports/{rid}/images", headers=a, files={"file": (name, data, ct)})  # noqa: E731
    assert up("x.txt", b"hello", "text/plain").status_code == 400
    assert up("x.jpg", b"not really an image", "image/jpeg").status_code == 400
    assert up("big.jpg", b"0" * (6 * 1024 * 1024), "image/jpeg").status_code == 413
    ok = up("x.png", make_image(fmt="PNG"), "image/png")
    assert ok.status_code == 201
    url = ok.json()["url"]
    assert client.get(url).status_code == 200  # signed URL works
    image_id = ok.json()["id"]
    assert client.get(f"/images/{image_id}?token=bad").status_code == 404
    assert client.get(f"/images/{image_id + 1}?token={create_image_token(image_id)}").status_code == 404


def test_image_token_cannot_be_used_as_login(client):
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {create_image_token(1)}"}).status_code == 401


def test_deleted_report_gone(client):
    a = register(client)
    rid = client.post("/reports", json=LOST_BACKPACK, headers=a).json()["id"]
    assert client.delete(f"/reports/{rid}", headers=a).status_code == 204
    assert client.get(f"/reports/{rid}", headers=a).status_code == 404


def test_admin_endpoints_protected_and_working(client):
    a = register(client)
    assert client.get("/admin/stats", headers=a).status_code == 403
    admin = make_admin(client)
    rid = client.post("/reports", json=LOST_BACKPACK, headers=a).json()["id"]
    stats = client.get("/admin/stats", headers=admin).json()
    assert stats["users"] == 2 and stats["reports_by_type"]["LOST"] == 1

    users = client.get("/admin/users", headers=admin).json()["users"]
    assert all("***@" in u["email"] for u in users)  # masked

    client.post("/flags", headers=admin, json={"entity_type": "report", "entity_id": rid, "reason": "Spam listing"})
    assert len(client.get("/admin/flags", headers=admin).json()["flags"]) == 1

    assert client.post(f"/admin/reports/{rid}/deactivate", headers=admin).json()["status"] == "DEACTIVATED"
    b = register(client, "Bob", "bob@example.com")
    assert client.get(f"/reports/{rid}", headers=b).status_code == 404
    assert client.get("/reports", headers=b).json()["total"] == 0

    alice_id = next(u["id"] for u in users if u["name"] == "Alice")
    client.post(f"/admin/users/{alice_id}/deactivate", headers=admin)
    assert client.get("/auth/me", headers=a).status_code == 401
    assert any(e["action"] == "admin.user_deactivated" for e in client.get("/admin/audit", headers=admin).json()["entries"])


def test_notifications_are_private(client):
    a = register(client)
    b = register(client, "Bob", "bob@example.com")
    from app.services.notifications import notify
    with SessionLocal() as db:
        n = notify(db, 1, "case_closed", item="x")
        db.commit()
        nid = n.id
    assert client.post(f"/notifications/{nid}/read", headers=b).status_code == 404
    assert client.get("/notifications", headers=a).json()["unread"] == 1
