"""Private image storage.

Files live outside any public/static folder and are only served through an
authenticated endpoint. Every upload is decoded with Pillow (rejecting non-images),
size-limited, and re-encoded, which strips EXIF metadata such as GPS coordinates.

Swap this module for an S3-compatible implementation by keeping the same functions.
"""

import io
import uuid
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import get_settings
from app.core.errors import AppError

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_DIMENSION = 2000


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


def save_image(data: bytes, content_type: str | None) -> tuple[str, dict, Image.Image]:
    """Validate and store an image. Returns (relative_path, metadata, decoded_image)."""
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
    name = f"{uuid.uuid4().hex}.jpg"
    # Re-encoding without passing exif= drops all metadata.
    img.save(_root() / name, format="JPEG", quality=85)
    return name, {"width": img.width, "height": img.height}, img


def open_image_path(relative: str) -> Path:
    root = _root()
    path = (root / relative).resolve()
    if root not in path.parents or not path.is_file():
        raise AppError(404, "Image not found")
    return path


def delete_image(relative: str) -> None:
    try:
        open_image_path(relative).unlink()
    except (AppError, OSError):
        pass
