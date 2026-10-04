"""Cloudinary photo storage, tested with MOCKED SDK calls and MOCKED signed-URL fetches.

No real credentials or network access are used. Real Cloudinary upload and retrieval are not covered here and
must be checked once with real credentials (see the deployment notes).
"""

import io
import urllib.error

import pytest
from PIL import Image
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.security import create_image_token
from app.services import storage
from tests.conftest import register
from tests.helpers import LOST_BACKPACK, make_image

cloudinary = pytest.importorskip("cloudinary")
import cloudinary.uploader  # noqa: E402

GPS_TAG = 0x8825


def _jpeg_with_gps() -> bytes:
    exif = Image.Exif()
    gps = exif.get_ifd(GPS_TAG)
    gps[1] = "N"
    gps[2] = (31.0, 34.0, 56.0)
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 30, 30)).save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


@pytest.fixture
def cloud(monkeypatch):
    """Turn Cloudinary on for one test and record every SDK and HTTP call. Restored after the test."""
    s = get_settings()
    monkeypatch.setattr(s, "cloudinary_cloud_name", "demo-cloud")
    monkeypatch.setattr(s, "cloudinary_api_key", "test-only-api-key")
    monkeypatch.setattr(s, "cloudinary_api_secret", "test-only-secret-not-real")
    calls = {"uploads": [], "destroys": [], "fetches": [], "payload": None, "fail_upload": False, "fail_read": None}

    def fake_upload(file, **options):
        if calls["fail_upload"]:
            raise RuntimeError("simulated network failure")
        data = file.read()
        calls["uploads"].append((data, options))
        calls["payload"] = data
        return {"public_id": options["public_id"]}

    def fake_destroy(public_id, **options):
        calls["destroys"].append((public_id, options))
        return {"result": "ok"}

    def fake_urlopen(url, timeout=None):
        calls["fetches"].append(url)
        if calls["fail_read"] is not None:
            raise urllib.error.HTTPError(url, calls["fail_read"], "simulated", None, None)
        return io.BytesIO(calls["payload"])

    monkeypatch.setattr(cloudinary.uploader, "upload", fake_upload)
    monkeypatch.setattr(cloudinary.uploader, "destroy", fake_destroy)
    monkeypatch.setattr(storage.urllib.request, "urlopen", fake_urlopen)
    return calls


def _stored_files() -> set:
    return {p.name for p in storage._root().iterdir()}


def test_cloud_upload_stores_reference_not_bytes_and_strips_gps(cloud):
    before = _stored_files()
    ref, meta, _ = storage.save_image(_jpeg_with_gps(), "image/jpeg")
    assert ref.startswith("cld:lostlink/") and len(ref) < 255  # the database keeps only this reference
    assert _stored_files() == before  # no local copy of the photo was written
    data, options = cloud["uploads"][0]
    uploaded = Image.open(io.BytesIO(data))
    assert uploaded.format == "JPEG"
    assert GPS_TAG not in uploaded.getexif()  # EXIF/GPS removed before upload
    assert options["type"] == "authenticated"  # never publicly delivered
    assert options["resource_type"] == "image" and options["overwrite"] is False
    assert meta["width"] > 0 and meta["height"] > 0


def test_cloud_read_is_signed_and_authenticated(cloud):
    storage.save_image(make_image(fmt="PNG"), "image/png")
    cloud["payload"] = make_image(fmt="JPEG")
    img = storage.load_image("cld:lostlink/abc123")
    assert img.size == (240, 240)
    url = cloud["fetches"][-1]
    assert "/image/authenticated/" in url and "/s--" in url  # signed authenticated delivery, server-side only


def test_cloud_missing_asset_is_404_and_outage_is_503(cloud):
    cloud["fail_read"] = 404
    with pytest.raises(AppError) as missing:
        storage.load_image("cld:lostlink/gone")
    assert missing.value.status_code == 404
    cloud["fail_read"] = 500
    with pytest.raises(AppError) as outage:
        storage.load_image("cld:lostlink/broken")
    assert outage.value.status_code == 503


def test_cloud_upload_failure_is_503_and_nothing_is_saved(cloud):
    cloud["fail_upload"] = True
    with pytest.raises(AppError) as err:
        storage.save_image(make_image(fmt="PNG"), "image/png")
    assert err.value.status_code == 503
    assert cloud["uploads"] == []


def test_cloud_delete_destroys_authenticated_asset(cloud):
    storage.delete_image("cld:lostlink/to-remove")
    public_id, options = cloud["destroys"][0]
    assert public_id == "lostlink/to-remove"
    assert options["type"] == "authenticated" and options["resource_type"] == "image"


def test_upload_limits_and_types_unchanged_in_cloud_mode(cloud):
    with pytest.raises(AppError) as too_big:
        storage.save_image(b"0" * (6 * 1024 * 1024), "image/jpeg")
    assert too_big.value.status_code == 413
    with pytest.raises(AppError) as wrong_type:
        storage.save_image(make_image(fmt="PNG"), "image/gif")
    assert wrong_type.value.status_code == 400
    assert cloud["uploads"] == []  # rejected before anything reaches Cloudinary


@pytest.mark.parametrize("fmt,ctype", [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")])
def test_supported_formats_upload_to_cloud(cloud, fmt, ctype):
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (10, 120, 200)).save(buf, format=fmt)
    ref, _, _ = storage.save_image(buf.getvalue(), ctype)
    assert ref.startswith("cld:")
    assert Image.open(io.BytesIO(cloud["uploads"][-1][0])).format == "JPEG"


def test_local_storage_is_used_when_cloudinary_is_not_configured(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "cloudinary_cloud_name", "")
    monkeypatch.setattr(s, "cloudinary_api_key", "")
    monkeypatch.setattr(s, "cloudinary_api_secret", "")
    assert s.cloudinary_configured is False
    before = _stored_files()
    name, _, _ = storage.save_image(_jpeg_with_gps(), "image/jpeg")
    assert not storage.is_cloud_ref(name) and name.endswith(".jpg")
    assert (storage._root() / name).is_file() and _stored_files() - before == {name}
    assert GPS_TAG not in Image.open(storage.open_image_path(name)).getexif()
    storage.delete_image(name)


def test_production_refuses_to_start_without_cloudinary():
    base = dict(_env_file=None, app_env="production", jwt_secret="x" * 40)
    with pytest.raises(ValidationError, match="Cloudinary is required"):
        Settings(**base)
    ok = Settings(**base, cloudinary_cloud_name="c", cloudinary_api_key="k", cloudinary_api_secret="s")
    assert ok.cloudinary_configured is True


def test_api_serves_cloud_photo_only_through_token(client, cloud):
    owner = register(client)
    rid = client.post("/reports", json=LOST_BACKPACK, headers=owner).json()["id"]
    up = client.post(f"/reports/{rid}/images", headers=owner,
                     files={"file": ("x.png", make_image(fmt="PNG"), "image/png")})
    assert up.status_code == 201
    image_id = up.json()["id"]
    url = up.json()["url"]
    assert url.startswith(f"/images/{image_id}?token=")  # the API never exposes a Cloudinary URL or reference
    for body in (up.text, client.get(f"/reports/{rid}", headers=owner).text):
        assert "cld:" not in body and "cloudinary" not in body.lower()
    served = client.get(url)
    assert served.status_code == 200 and served.headers["content-type"] == "image/jpeg"
    assert client.get(f"/images/{image_id}?token=bad").status_code == 404
    assert client.get(f"/images/{image_id}?token={create_image_token(image_id + 1)}").status_code == 404
    assert client.get(f"/images/{image_id}").status_code == 422  # token is required


def test_recompute_reads_cloud_photos_for_embeddings(client, cloud):
    from app.db.session import SessionLocal
    from app.models import ItemImage
    from scripts.recompute_image_embeddings import recompute

    owner = register(client)
    rid = client.post("/reports", json=LOST_BACKPACK, headers=owner).json()["id"]
    image_id = client.post(f"/reports/{rid}/images", headers=owner,
                           files={"file": ("x.png", make_image(fmt="PNG"), "image/png")}).json()["id"]
    with SessionLocal() as db:
        db.get(ItemImage, image_id).embedding = {"model": "stale-model", "dim": 2, "vec": [1.0, 0.0]}
        db.commit()
    fetches_before = len(cloud["fetches"])
    with SessionLocal() as db:
        counts = recompute(db, only_stale=True)
        db.commit()
    with SessionLocal() as db:
        row = db.get(ItemImage, image_id)
    assert counts["updated"] == 1 and counts["failed"] == 0
    assert row.embedding["model"] != "stale-model" and len(row.embedding["vec"]) == row.embedding["dim"]
    assert len(cloud["fetches"]) == fetches_before + 1  # the photo was read back through the Cloudinary adapter
