"""Recompute stored photo embeddings with the active embedder (for example, after the learned model is installed).

    python -m scripts.recompute_image_embeddings            # every photo whose embedding is not from the active model
    python -m scripts.recompute_image_embeddings --all      # recompute every photo

Photos are read from the existing private storage (app/services/storage.py). A photo that cannot be read or embedded
keeps its old embedding and is counted as failed. Nothing is deleted. The result is a rebuildable derived value.
"""

import argparse
import logging
from collections import Counter

from PIL import Image
from sqlalchemy import select

from app.ai.providers import get_image_embedder
from app.db.session import SessionLocal
from app.models import ItemImage
from app.services import storage
from app.services.storage import flatten_for_storage

log = logging.getLogger("lostlink.vision")


def recompute(db, embedder=None, only_stale: bool = True) -> Counter:
    """Return counts: updated, skipped (already current), failed. Caller commits."""
    embedder = embedder or get_image_embedder()
    counts: Counter = Counter()
    for image in db.scalars(select(ItemImage).order_by(ItemImage.id)).all():
        current = isinstance(image.embedding, dict) and image.embedding.get("model") == embedder.name
        if only_stale and current:
            counts["skipped"] += 1
            continue
        try:
            with Image.open(storage.open_image_path(image.storage_path)) as img:
                img.load()
                image.embedding = embedder.embed(flatten_for_storage(img))
            counts["updated"] += 1
        except Exception as exc:  # unreadable file, missing file, inference failure
            log.warning("could not recompute image %s: %s", image.id, exc.__class__.__name__)
            counts["failed"] += 1
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="recompute every photo, not only stale ones")
    args = ap.parse_args()
    with SessionLocal() as db:
        counts = recompute(db, only_stale=not args.all)
        db.commit()
    print(f"updated={counts['updated']} skipped={counts['skipped']} failed={counts['failed']}")


if __name__ == "__main__":
    main()
