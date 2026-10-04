"""Learned visual embeddings: preprocessing, model, similarity, aggregation, fallback, integration and privacy.

Tests that need the model file are skipped with a clear reason when it is not installed
(run `python -m scripts.fetch_vision_model`). The fallback and aggregation tests run without the model.
"""

import io
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.ai.providers import image_method
from app.ai.providers import vision as vision_mod
from app.ai.providers.image import HeuristicImageEmbedder
from app.ai.providers.vision import EMBED_DIM, OnnxVisionEmbedder, VisionUnavailable, default_model_path, preprocess
from app.ai.visual import visual_evidence
from app.core.errors import AppError
from app.core.security import create_image_token
from app.services import storage
from tests.conftest import register
from tests.helpers import LOST_BACKPACK

MODEL_PRESENT = default_model_path().is_file()
needs_model = pytest.mark.skipif(not MODEL_PRESENT, reason="model file missing: run python -m scripts.fetch_vision_model")


def _scene(colour, shape="rect", bg=(235, 235, 235), size=(240, 240)) -> Image.Image:
    img = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(img)
    if shape == "rect":
        d.rectangle((50, 60, 190, 180), fill=colour)
    else:
        d.ellipse((50, 60, 190, 180), fill=colour)
    return img


def _encode(img: Image.Image, fmt: str, **kw) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt, **kw)
    return buf.getvalue()


@pytest.fixture
def clean_provider_cache():
    from app.ai.providers import _learned_embedder
    _learned_embedder.cache_clear()
    yield
    _learned_embedder.cache_clear()


@pytest.fixture
def learned():
    if not MODEL_PRESENT:
        pytest.skip("model file missing")
    return OnnxVisionEmbedder.load(default_model_path(), "cpu")


# ---- preprocessing and image formats ------------------------------------------------------------------

def test_preprocess_shape_dtype_and_range():
    x = preprocess(_scene((120, 60, 30)))
    assert x.shape == (1, 3, 224, 224) and x.dtype == np.float32
    assert -2.2 < float(x.min()) and float(x.max()) < 2.7  # ImageNet-normalised range


@pytest.mark.parametrize("mode", ["RGB", "RGBA", "L", "P"])
def test_preprocess_accepts_common_modes(mode):
    base = _scene((200, 40, 40))
    if mode == "RGBA":
        base = base.convert("RGBA")
        base.putalpha(128)
    elif mode == "L":
        base = base.convert("L")
    elif mode == "P":
        base = base.convert("P")
    assert preprocess(base).shape == (1, 3, 224, 224)


def test_transparent_pixels_are_composited_onto_white():
    img = Image.new("RGBA", (50, 50), (255, 0, 0, 0))  # fully transparent red
    flat = storage.flatten_for_storage(img)
    assert flat.mode == "RGB" and flat.getpixel((5, 5)) == (255, 255, 255)


@pytest.mark.parametrize("fmt,ctype,kwargs", [("JPEG", "image/jpeg", {}), ("PNG", "image/png", {}),
                                              ("WEBP", "image/webp", {"quality": 90})])
def test_supported_formats_are_stored_as_jpeg(fmt, ctype, kwargs):
    data = _encode(_scene((30, 90, 200)), fmt, **kwargs)
    path, meta, img = storage.save_image(data, ctype)
    assert path.endswith(".jpg") and meta["width"] > 0 and img.mode == "RGB"


def test_exif_orientation_is_applied_before_metadata_is_dropped():
    img = Image.new("RGB", (200, 100), (10, 10, 10))  # landscape pixels
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 degrees clockwise when displayed
    data = _encode(img, "JPEG", exif=exif.tobytes())
    _, meta, _ = storage.save_image(data, "image/jpeg")
    assert (meta["width"], meta["height"]) == (100, 200)  # stored upright


def test_gps_and_other_metadata_are_not_kept():
    exif = Image.Exif()
    exif[0x8825] = {1: "N", 2: (31.0, 34.0, 50.0)}  # GPS IFD
    exif[0x010F] = "Test camera"
    data = _encode(_scene((90, 90, 90)), "JPEG", exif=exif.tobytes())
    path, _, _ = storage.save_image(data, "image/jpeg")
    stored = Image.open(storage.open_image_path(path))
    assert len(stored.getexif()) == 0 and "exif" not in stored.info


def test_corrupt_image_is_refused_cleanly():
    with pytest.raises(AppError) as err:
        storage.save_image(b"this is not an image", "image/jpeg")
    assert err.value.status_code == 400


def test_empty_upload_is_refused():
    with pytest.raises(AppError):
        storage.save_image(b"", "image/png")


def test_missing_photos_give_unavailable_evidence_not_a_score():
    assert visual_evidence([], []) == {"available": False, "reason": "no photos on one or both reports"}


# ---- model, dimension, normalisation, similarity ------------------------------------------------------

@needs_model
def test_model_loads_on_cpu_and_reports_its_device(learned):
    assert learned.device == "cpu" and learned.name.startswith("onnx-")


@needs_model
def test_cuda_path_is_used_only_when_available():
    import onnxruntime as ort
    if "CUDAExecutionProvider" not in ort.get_available_providers():
        pytest.skip("no CUDA execution provider on this machine")
    assert OnnxVisionEmbedder.load(default_model_path(), "cuda").device == "cuda"


@needs_model
def test_embedding_has_expected_dimension_and_unit_norm(learned):
    e = learned.embed(_scene((120, 60, 30)))
    assert e["dim"] == EMBED_DIM == len(e["vec"])
    assert abs(np.linalg.norm(np.asarray(e["vec"])) - 1.0) < 1e-3


@needs_model
def test_embedding_is_deterministic(learned):
    img = _scene((120, 60, 30), shape="ellipse")
    assert learned.embed(img)["vec"] == learned.embed(img)["vec"]


@needs_model
def test_same_image_similarity_is_one_and_different_objects_are_lower(learned):
    a = learned.embed(_scene((120, 60, 30)))
    assert learned.similarity(a, learned.embed(_scene((120, 60, 30)))) == pytest.approx(1.0, abs=1e-3)
    far = learned.embed(_scene((20, 200, 20), shape="ellipse", bg=(20, 20, 20)))
    assert learned.similarity(a, far) < 0.999


@needs_model
def test_similarity_is_symmetric_and_bounded(learned):
    a = learned.embed(_scene((10, 10, 200)))
    b = learned.embed(_scene((200, 180, 20), shape="ellipse"))
    s_ab, s_ba = learned.similarity(a, b), learned.similarity(b, a)
    assert s_ab == pytest.approx(s_ba) and 0.0 <= s_ab <= 1.0


def test_embeddings_from_different_models_are_not_compared():
    fake = {"model": "onnx-some-other-model", "dim": EMBED_DIM, "vec": [0.1] * EMBED_DIM}
    heur = HeuristicImageEmbedder().embed(_scene((120, 60, 30)))
    assert OnnxVisionEmbedder(session=None, device="cpu").similarity(fake, fake) == 0.0
    assert HeuristicImageEmbedder().similarity(heur, fake) == 0.0


def test_malformed_vector_gives_zero_not_an_error():
    bad = {"model": vision_mod.MODEL_NAME, "dim": EMBED_DIM, "vec": [1.0, 2.0]}
    assert OnnxVisionEmbedder(session=None, device="cpu").similarity(bad, bad) == 0.0


# ---- multiple images (aggregation, no model needed) ------------------------------------------------------

class _FakeEmbedder:
    name = "fake-model"
    device = "cpu"

    def __init__(self, table):
        self.table = table

    def similarity(self, a, b):
        return self.table.get((a["id"], b["id"]), 0.0)


def _photo(i):
    return SimpleNamespace(embedding={"id": i, "model": "fake-model"})


def _found(i):
    return SimpleNamespace(embedding={"id": i, "model": "fake-model"})


def test_one_accidental_match_cannot_set_the_visual_result(monkeypatch):
    # three lost photos, two found; only one pair matches strongly by accident
    table = {(0, 10): 0.95, (0, 11): 0.20, (1, 10): 0.22, (1, 11): 0.18, (2, 10): 0.25, (2, 11): 0.21}
    monkeypatch.setattr("app.ai.visual.get_image_embedder", lambda: _FakeEmbedder(table))
    ev = visual_evidence([_photo(0), _photo(1), _photo(2)], [_found(10), _found(11)])
    assert ev["available"] and ev["similarity"] < 0.5
    assert ev["image_count"] == {"lost": 3, "found": 2}


def test_consistent_matches_across_several_photos_agree(monkeypatch):
    table = {(0, 10): 0.9, (1, 10): 0.88, (0, 11): 0.86, (1, 11): 0.91}
    monkeypatch.setattr("app.ai.visual.get_image_embedder", lambda: _FakeEmbedder(table))
    ev = visual_evidence([_photo(0), _photo(1)], [_found(10), _found(11)])
    assert ev["similarity"] >= 0.85


def test_single_pair_is_reported_as_is(monkeypatch):
    monkeypatch.setattr("app.ai.visual.get_image_embedder", lambda: _FakeEmbedder({(0, 10): 0.83}))
    assert visual_evidence([_photo(0)], [_found(10)])["similarity"] == pytest.approx(0.83, abs=1e-3)


def test_different_model_embeddings_are_reported_unavailable(monkeypatch):
    monkeypatch.setattr("app.ai.visual.get_image_embedder", lambda: _FakeEmbedder({}))
    lost = [SimpleNamespace(embedding={"id": 0, "model": "color-dhash-v1"})]
    found = [SimpleNamespace(embedding={"id": 10, "model": "color-dhash-v1"})]
    assert visual_evidence(lost, found) == {"available": False,
                                            "reason": "stored photo embeddings come from a different model"}


# ---- fallback and configuration ----------------------------------------------------------------------

def test_missing_model_file_falls_back_to_the_heuristic(monkeypatch, clean_provider_cache):
    from app.ai import providers

    def fail_to_load(cls, *args, **kwargs):
        raise VisionUnavailable("model file not found")
    monkeypatch.setattr(vision_mod.OnnxVisionEmbedder, "load", classmethod(fail_to_load))
    emb = providers.get_image_embedder()
    assert isinstance(emb, HeuristicImageEmbedder) and image_method(emb) == "heuristic"


@needs_model
def test_inference_failure_does_not_crash_upload(monkeypatch, clean_provider_cache, client):
    def boom(self, img):
        raise RuntimeError("inference failed")
    monkeypatch.setattr(vision_mod.OnnxVisionEmbedder, "embed", boom)
    headers = register(client, "Ayesha", "vision-owner@example.com")
    report = client.post("/reports", json=LOST_BACKPACK, headers=headers).json()
    buf = io.BytesIO()
    _scene((60, 60, 200)).save(buf, format="JPEG")
    r = client.post(f"/reports/{report['id']}/images", headers=headers,
                    files={"file": ("p.jpg", buf.getvalue(), "image/jpeg")})
    assert r.status_code == 201  # the upload still succeeds; the photo simply has no visual embedding


def test_cv_can_be_disabled_by_settings(monkeypatch, clean_provider_cache):
    from app.ai import providers
    monkeypatch.setattr(providers.get_settings(), "vision_enabled", False)
    assert isinstance(providers.get_image_embedder(), HeuristicImageEmbedder)


def test_heuristic_provider_can_be_selected_explicitly(monkeypatch, clean_provider_cache):
    from app.ai import providers
    monkeypatch.setattr(providers.get_settings(), "vision_provider", "heuristic")
    assert isinstance(providers.get_image_embedder(), HeuristicImageEmbedder)


# ---- integration with the existing matcher ------------------------------------------------------------

@needs_model
def test_learned_evidence_reaches_the_matcher_as_corroboration(clean_provider_cache):
    from app.ai.providers import get_image_embedder
    from tests.test_ai_units import report
    from tests.test_scoring_v3 import _same_spot, _score

    embedder = get_image_embedder()
    assert image_method(embedder) == "learned"
    pic = _scene((120, 60, 30))
    lost = report(category="Wallet", name="Wallet", description="brown wallet", color="brown", **_same_spot())
    found = report(category="Wallet", name="Wallet", description="brown wallet", color="brown", **_same_spot())
    lost.images = [SimpleNamespace(embedding=embedder.embed(pic))]
    found.images = [SimpleNamespace(embedding=embedder.embed(pic))]
    res = _score(lost, found)
    assert res.signals["image"] == pytest.approx(1.0, abs=1e-3)
    assert any("learned visual model" in e["text"] for e in res.evidence)
    assert res.notify_eligible is False  # a visual match alone never notifies


# ---- privacy ----------------------------------------------------------------------------------------

@needs_model
def test_embeddings_are_not_exposed_through_any_api_response(client, clean_provider_cache):
    headers = register(client, "Ayesha", "vision-privacy@example.com")
    report = client.post("/reports", json=LOST_BACKPACK, headers=headers).json()
    buf = io.BytesIO()
    _scene((60, 60, 200)).save(buf, format="JPEG")
    client.post(f"/reports/{report['id']}/images", headers=headers,
                files={"file": ("p.jpg", buf.getvalue(), "image/jpeg")})
    body = client.get(f"/reports/{report['id']}", headers=headers).json()
    assert '"vec"' not in str(body) and "embedding" not in str(body)


@needs_model
def test_served_photo_has_no_gps_metadata(client, clean_provider_cache):
    headers = register(client, "Ayesha", "vision-exif@example.com")
    report = client.post("/reports", json=LOST_BACKPACK, headers=headers).json()
    exif = Image.Exif()
    exif[0x8825] = {1: "N", 2: (31.0, 34.0, 50.0)}  # GPS coordinates in the original upload
    buf = io.BytesIO()
    _scene((60, 60, 200)).save(buf, format="JPEG", exif=exif.tobytes())
    up = client.post(f"/reports/{report['id']}/images", headers=headers,
                     files={"file": ("p.jpg", buf.getvalue(), "image/jpeg")})
    assert up.status_code == 201
    image_id = up.json()["id"]
    served = client.get(f"/images/{image_id}?token={create_image_token(image_id)}")
    assert served.status_code == 200
    assert len(Image.open(io.BytesIO(served.content)).getexif()) == 0
    assert "storage" not in str(report).lower()  # no private file path in the report


# ---- rebuildable embeddings -----------------------------------------------------------------------------

@needs_model
def test_recompute_replaces_stale_embeddings_and_counts_missing_files(client, clean_provider_cache):
    import os
    from app.db.session import SessionLocal
    from app.models import ItemImage
    from app.services import storage
    from app.ai.providers import get_image_embedder
    from scripts.recompute_image_embeddings import recompute

    headers = register(client, "Ayesha", "vision-recompute@example.com")
    report = client.post("/reports", json=LOST_BACKPACK, headers=headers).json()
    buf = io.BytesIO()
    _scene((60, 60, 200)).save(buf, format="JPEG")
    up = client.post(f"/reports/{report['id']}/images", headers=headers,
                     files={"file": ("p.jpg", buf.getvalue(), "image/jpeg")})
    image_id = up.json()["id"]
    with SessionLocal() as db:
        row = db.get(ItemImage, image_id)
        row.embedding = {"model": "color-dhash-v1", "hist": [0.0], "dhash": "0" * 16}  # a stale heuristic embedding
        db.commit()
    with SessionLocal() as db:
        counts = recompute(db, get_image_embedder())
        db.commit()
        assert counts["updated"] >= 1
        assert db.get(ItemImage, image_id).embedding["model"] == get_image_embedder().name
    # a stored file that has gone missing is counted as failed and nothing is deleted
    with SessionLocal() as db:
        row = db.get(ItemImage, image_id)
        row.embedding = None
        path = storage.open_image_path(row.storage_path)
        db.commit()
    os.remove(path)
    with SessionLocal() as db:
        counts = recompute(db, get_image_embedder())
        assert counts["failed"] >= 1
        assert db.get(ItemImage, image_id).embedding is None  # the old value is kept when recomputation fails
