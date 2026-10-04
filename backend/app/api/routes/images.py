from fastapi import APIRouter

from app.api.deps import DB
from app.core.errors import not_found
from app.core.security import decode_image_token
from app.models import ItemImage
from app.services import storage

router = APIRouter(tags=["images"])


@router.get("/images/{image_id}")
def get_image(image_id: int, token: str, db: DB):
    """Serve a private image. The short-lived token is only issued to users allowed to view the report."""
    if decode_image_token(token) != image_id:
        raise not_found("Image")
    image = db.get(ItemImage, image_id)
    if image is None:
        raise not_found("Image")
    return storage.serve_image(image.storage_path, image.content_type)
