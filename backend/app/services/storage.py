"""Private image storage.

Files are never served from a public folder. Each image is served only through an authenticated endpoint
(app/api/routes/images.py). Every upload is decoded with Pillow (rejecting non-images), size-limited, and
re-encoded, which strips EXIF metadata such as GPS coordinates. The re-encoded bytes are what gets stored.

Two backends share these functions:
- Local filesystem (default, development): files under STORAGE_DIR, referenced by file name.
- Cloudinary (production, when CLOUDINARY_* is configured): uploaded as AUTHENTICATED assets, which are never
  publicly delivered. The database keeps only a reference ("cld:<public_id>"), never the image bytes. The server
  fetches the bytes with a signed URL and returns them only after the usual token check.
"""

import io
import logging
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from fastapi.responses import FileResponse, Response
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import get_settings
from app.core.errors import AppError

log = logging.getLogger("lostlink.storage")

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_DIMENSION = 2000
CLOUD_PREFIX = "cld:"
CLOUD_FOLDER = "lostlink"
CLOUD_READ_LIMIT = 10 * 1024 * 1024  # re-encoded photos are far smaller than this


def flatten_for_storage(img: Image.Image) -> Image.Image:
    """Return an upright RGB image. EXIF orientation is applied first (phone photos are often stored rotated),
    then transparency is composited onto white, so transparent pixels do not keep arbitrary colours."""
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return img.convert("RGB")


def _root() -> Path:
    root = Path(get_settings().storage_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def is_cloud_ref(relative: str) -> bool:
    return relative.startswith(CLOUD_PREFIX)


def save_image(data: bytes, content_type: str | None) -> tuple[str, dict, Image.Image]:
    """Validate and store an image. Returns (stored_reference, metadata, decoded_image)."""
    s = get_settings()
    if content_type not in ALLOWED_TYPES:
        raise AppError(400, "Only JPEG, PNG or WebP images are allowed")
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise AppError(413, f"Image is too large (max {s.max_upload_mb} MB)")
    if not data:
        raise AppError(400, "Image file is empty")
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError):
        raise AppError(400, "The file is not a valid image")

    img = flatten_for_storage(img)
    img.thumbnail((MAX_DIMENSION, MAX_DIMENSION))
    # Re-encoding without passing exif= drops all metadata.
    encoded = io.BytesIO()
    img.save(encoded, format="JPEG", quality=85)
    meta = {"width": img.width, "height": img.height}
    if s.cloudinary_configured:
        return CLOUD_PREFIX + _cloud_upload(encoded.getvalue()), meta, img
    name = f"{uuid.uuid4().hex}.jpg"
    (_root() / name).write_bytes(encoded.getvalue())
    return name, meta, img


def open_image_path(relative: str) -> Path:
    """Local files only. Cloudinary-backed photos have no local path; use serve_image or load_image."""
    root = _root()
    path = (root / relative).resolve()
    if root not in path.parents or not path.is_file():
        raise AppError(404, "Image not found")
    return path


def serve_image(relative: str, media_type: str) -> Response:
    headers = {"Cache-Control": "private, max-age=600"}
    if is_cloud_ref(relative):
        return Response(content=_cloud_read(relative[len(CLOUD_PREFIX):]), media_type=media_type, headers=headers)
    return FileResponse(open_image_path(relative), media_type=media_type, headers=headers)


def load_image(relative: str) -> Image.Image:
    """Decode a stored photo into memory (used to recompute embeddings). Raises if it cannot be read."""
    if is_cloud_ref(relative):
        img = Image.open(io.BytesIO(_cloud_read(relative[len(CLOUD_PREFIX):])))
        img.load()
        return img
    with Image.open(open_image_path(relative)) as img:
        img.load()
        return img.copy()


def delete_image(relative: str) -> None:
    if is_cloud_ref(relative):
        _cloud_destroy(relative[len(CLOUD_PREFIX):])
        return
    try:
        open_image_path(relative).unlink()
    except (AppError, OSError):
        pass


# --- Cloudinary adapter. The SDK is imported here so that local development does not need it configured. ---

def _cloud_configure():
    import cloudinary
    import cloudinary.uploader  # noqa: F401  (registers the uploader module)
    import cloudinary.utils  # noqa: F401

    s = get_settings()
    cloudinary.config(cloud_name=s.cloudinary_cloud_name, api_key=s.cloudinary_api_key,
                      api_secret=s.cloudinary_api_secret, secure=True)
    return cloudinary


def _cloud_upload(data: bytes) -> str:
    cloudinary = _cloud_configure()
    public_id = f"{CLOUD_FOLDER}/{uuid.uuid4().hex}"
    try:
        result = cloudinary.uploader.upload(io.BytesIO(data), public_id=public_id, type="authenticated",
                                            resource_type="image", filename=f"{public_id}.jpg",
                                            overwrite=False, unique_filename=False, use_filename=False)
    except Exception as exc:  # network or credential failure; the report is not saved
        log.warning("photo upload to storage failed: %s", exc.__class__.__name__)
        raise AppError(503, "Photo storage is temporarily unavailable. Please try again.")
    return result["public_id"]


def _cloud_read(public_id: str) -> bytes:
    cloudinary = _cloud_configure()
    # Signed, so only this server can fetch it. The URL is never returned to a client.
    url, _ = cloudinary.utils.cloudinary_url(public_id, type="authenticated", resource_type="image",
                                             sign_url=True, secure=True)
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = resp.read(CLOUD_READ_LIMIT + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise AppError(404, "Image not found")
        log.warning("photo read from storage failed: HTTP %s", exc.code)
        raise AppError(503, "The image is temporarily unavailable.")
    except Exception as exc:
        log.warning("photo read from storage failed: %s", exc.__class__.__name__)
        raise AppError(503, "The image is temporarily unavailable.")
    if len(data) > CLOUD_READ_LIMIT:
        raise AppError(503, "The image is temporarily unavailable.")
    return data


def _cloud_destroy(public_id: str) -> None:
    cloudinary = _cloud_configure()
    try:
        cloudinary.uploader.destroy(public_id, type="authenticated", resource_type="image", invalidate=True)
    except Exception as exc:  # the database row is already gone; a leftover asset is logged, not fatal
        log.warning("photo delete from storage failed: %s", exc.__class__.__name__)
