"""UET Lahore geofence: unit tests, backend validation, legacy data and matching."""

import tempfile
from datetime import datetime, timezone

from sqlalchemy import create_engine, inspect, text

from app.db.migrate import run_migrations
from app.db.session import SessionLocal
from app.geo.geofence import (CAMPUS, NEARBY, OUT_OF_AREA_MESSAGE, classify, distance_to_polygon_m, get_geofence,
                              point_in_polygon)
from app.models import ItemReport, User
from app.models.enums import ReportType
from tests.conftest import register
from tests.helpers import CAMPUS_POINT, FOUND_BACKPACK, LOST_BACKPACK, NEARBY_POINT, OUTSIDE_POINT

BASE = {k: v for k, v in LOST_BACKPACK.items() if k not in ("location", "place_key")}


def create(client, headers, **location):
    return client.post("/reports", headers=headers, json={**BASE, **location})


# ---------- geometry ----------

def test_polygon_math_on_simple_square():
    square = [(0.0, 0.0), (0.0, 0.01), (0.01, 0.01), (0.01, 0.0)]
    assert point_in_polygon(0.005, 0.005, square)
    assert not point_in_polygon(0.02, 0.005, square)
    # 0.001 deg latitude ~ 111 m outside the top edge
    assert 100 < distance_to_polygon_m(0.011, 0.005, square) < 122


def test_config_is_the_osm_campus():
    f = get_geofence()
    assert f.id == "uet-lahore" and len(f.polygon) > 50
    assert "OpenStreetMap" in f.attribution
    assert all(classify(p.lat, p.lng) in (CAMPUS, NEARBY) for p in f.places)  # every place is inside the fence


def test_zones():
    assert classify(*CAMPUS_POINT) == CAMPUS
    assert classify(*NEARBY_POINT) == NEARBY
    assert classify(*OUTSIDE_POINT) is None
    assert classify(31.5216, 74.4036) is None  # Lahore airport
    gate = get_geofence().place("gate-2")
    assert classify(gate.lat, gate.lng) == CAMPUS  # gates lie on the boundary wall


# ---------- backend validation (scenarios 1-6) ----------

def test_predefined_place_uses_server_coordinates(client):
    h = register(client)
    # Client-sent coordinates are ignored for predefined places
    r = create(client, h, place_key="gate-3", latitude=OUTSIDE_POINT[0], longitude=OUTSIDE_POINT[1])
    assert r.status_code == 201, r.text
    body = r.json()
    gate = get_geofence().place("gate-3")
    assert (body["latitude"], body["longitude"]) == (gate.lat, gate.lng)
    assert body["zone"] == "campus" and body["location_type"] == "predefined" and body["location"] == "Gate 3"


def test_valid_campus_gps(client):
    h = register(client)
    r = create(client, h, location_type="gps", latitude=CAMPUS_POINT[0], longitude=CAMPUS_POINT[1])
    assert r.status_code == 201, r.text
    assert r.json()["zone"] == "campus"
    assert r.json()["location"] == "Near Department of Civil Engineering"  # auto label, no coordinates


def test_valid_nearby_gps(client):
    h = register(client)
    r = create(client, h, location_type="gps", location="G.T. Road bus stop",
               latitude=NEARBY_POINT[0], longitude=NEARBY_POINT[1])
    assert r.status_code == 201, r.text
    assert r.json()["zone"] == "nearby" and r.json()["location"] == "G.T. Road bus stop"


def test_outside_point_rejected(client):
    h = register(client)
    r = create(client, h, location_type="gps", location="Minar-e-Pakistan",
               latitude=OUTSIDE_POINT[0], longitude=OUTSIDE_POINT[1])
    assert r.status_code == 422
    assert r.json()["detail"] == OUT_OF_AREA_MESSAGE


def test_free_text_only_rejected(client):
    h = register(client)
    r = create(client, h, location="Liberty Market, Gulberg")
    assert r.status_code == 422
    assert "UET Lahore location" in r.json()["detail"]


def test_missing_location_rejected(client):
    h = register(client)
    assert create(client, h).status_code == 422
    assert create(client, h, place_key="not-a-real-place").status_code == 422


def test_update_cannot_move_outside(client):
    h = register(client)
    rid = create(client, h, place_key="lecture-theatre").json()["id"]
    r = client.put(f"/reports/{rid}", headers=h, json={"latitude": OUTSIDE_POINT[0], "longitude": OUTSIDE_POINT[1],
                                                        "location_type": "map", "place_key": None})
    assert r.status_code == 422
    # Relabelling keeps the validated point
    r = client.put(f"/reports/{rid}", headers=h, json={"location": "Steps of the Lecture Theatre"})
    assert r.status_code == 200
    assert r.json()["location"] == "Steps of the Lecture Theatre" and r.json()["place_key"] == "lecture-theatre"
    # Moving to another valid place works and recomputes the zone
    r = client.put(f"/reports/{rid}", headers=h, json={"location_type": "gps", "place_key": None,
                                                        "latitude": NEARBY_POINT[0], "longitude": NEARBY_POINT[1]})
    assert r.status_code == 200 and r.json()["zone"] == "nearby"


def test_geo_endpoints(client):
    assert client.get("/geo/config").status_code == 401
    h = register(client)
    cfg = client.get("/geo/config", headers=h).json()
    assert len(cfg["campus_polygon"]) > 50 and cfg["nearby_buffer_m"] == 500
    assert any(p["key"] == "lecture-theatre" for p in cfg["places"])
    ok = client.get(f"/geo/resolve?lat={CAMPUS_POINT[0]}&lng={CAMPUS_POINT[1]}", headers=h).json()
    assert ok["allowed"] and ok["zone"] == "campus"
    bad = client.get(f"/geo/resolve?lat={OUTSIDE_POINT[0]}&lng={OUTSIDE_POINT[1]}", headers=h).json()
    assert not bad["allowed"] and bad["message"] == OUT_OF_AREA_MESSAGE


# ---------- legacy data (scenario 10) ----------

def test_migration_upgrades_pre_geofence_database():
    """A database created before migrations/structured location keeps its reports."""
    url = f"sqlite:///{tempfile.mkdtemp()}/legacy.db"
    eng = create_engine(url)
    run_migrations(eng, target="0001")  # old schema
    with eng.begin() as conn:
        conn.execute(text("DROP TABLE alembic_version"))  # simulate the pre-Alembic create_all database
        conn.execute(text("INSERT INTO users (id, name, email, password_hash, role, is_active, created_at, updated_at) "
                          "VALUES (1, 'Old', 'old@x.com', 'x', 'USER', 1, '2026-01-01', '2026-01-01')"))
        conn.execute(text(
            "INSERT INTO item_reports (id, user_id, report_type, category, name, description, date_time, location, "
            "status, ai_status, created_at, updated_at) VALUES (1, 1, 'LOST', 'Wallet', 'Brown wallet', "
            "'Old report', '2026-01-01', 'Somewhere', 'ACTIVE', 'DONE', '2026-01-01', '2026-01-01')"))
    run_migrations(eng)  # stamps baseline, applies 0002
    cols = {c["name"] for c in inspect(eng).get_columns("item_reports")}
    assert {"zone", "location_type", "place_key"} <= cols
    with eng.connect() as conn:
        row = conn.execute(text("SELECT location, zone FROM item_reports WHERE id = 1")).one()
        assert row == ("Somewhere", None)
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0003"  # current head
    eng.dispose()


def test_legacy_report_still_works(client):
    h = register(client)
    with SessionLocal() as db:
        uid = db.query(User).one().id
        r = ItemReport(user_id=uid, report_type=ReportType.LOST, category="Wallet", name="Brown wallet",
                       description="Created before the geofence", date_time=datetime(2026, 9, 1, tzinfo=timezone.utc),
                       location="Old free-text place", latitude=33.6425, longitude=72.993)
        db.add(r)
        db.commit()
        rid = r.id
    view = client.get(f"/reports/{rid}", headers=h).json()
    assert view["zone"] is None and view["location"] == "Old free-text place"
    # Non-location edits still work; matching can run on it
    assert client.put(f"/reports/{rid}", headers=h, json={"color": "Brown"}).status_code == 200
    assert client.post(f"/reports/{rid}/match", headers=h).status_code == 200
    assert client.get("/reports?mine=true", headers=h).json()["total"] == 1


# ---------- matching ----------

def test_matching_uses_campus_proximity(client):
    owner = register(client, "Owner", "o@example.com")
    finder = register(client, "Finder", "f@example.com")
    lost = client.post("/reports", headers=owner, json=LOST_BACKPACK).json()
    client.post("/reports", headers=finder, json=FOUND_BACKPACK)
    m = client.get(f"/reports/{lost['id']}/matches", headers=owner).json()["matches"][0]
    assert m["signals"]["location"] > 0.8
    assert any(" m from where it was lost" in e for e in m["explanation"])
    assert "Both on UET Lahore campus" in m["explanation"]


def test_matching_same_place_and_same_area(client):
    owner = register(client, "Owner", "o@example.com")
    finder = register(client, "Finder", "f@example.com")
    lost = client.post("/reports", headers=owner, json={**LOST_BACKPACK, "place_key": "swimming-pool",
                                                         "location": None}).json()
    found = {**FOUND_BACKPACK, "place_key": "sports-grounds", "location": None}
    client.post("/reports", headers=finder, json=found)
    m = client.get(f"/reports/{lost['id']}/matches", headers=owner).json()["matches"][0]
    assert m["signals"]["location"] >= 0.8  # pool and courts are in the same 'sports' area

    finder2 = register(client, "Finder2", "f2@example.com")
    client.post("/reports", headers=finder2, json={**found, "place_key": "swimming-pool"})
    ms = client.get(f"/reports/{lost['id']}/matches", headers=owner).json()["matches"]
    assert any("Both reported at Swimming Pool" in e for m2 in ms for e in m2["explanation"])
