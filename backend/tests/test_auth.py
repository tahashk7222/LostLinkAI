from tests.conftest import register


def test_register_login_me(client):
    headers = register(client)
    r = client.get("/auth/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["email"] == "alice@example.com"
    assert "password_hash" not in r.json()

    r = client.post("/auth/login", json={"email": "ALICE@example.com", "password": "password123"})
    assert r.status_code == 200
    assert r.json()["access_token"]


def test_duplicate_email_rejected(client):
    register(client)
    r = client.post("/auth/register", json={"name": "A2", "email": "alice@example.com", "password": "password123"})
    assert r.status_code == 409


def test_wrong_password(client):
    register(client)
    r = client.post("/auth/login", json={"email": "alice@example.com", "password": "wrongpass1"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Incorrect email or password"


def test_me_requires_auth(client):
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_password_is_hashed(client):
    from app.db.session import SessionLocal
    from app.models import User

    register(client)
    with SessionLocal() as db:
        u = db.query(User).first()
        assert u.password_hash != "password123"
        assert u.password_hash.startswith("$2")


def test_short_password_rejected(client):
    r = client.post("/auth/register", json={"name": "Bob", "email": "bob@example.com", "password": "short"})
    assert r.status_code == 422


def test_health(client):
    assert client.get("/health").json()["database"] is True
