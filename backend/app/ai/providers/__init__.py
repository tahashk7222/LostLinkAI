"""Pluggable embedding providers.

Text: hashed-vector embedder (no model). Image: the learned ONNX embedder when it can load, otherwise the
colour-histogram + difference-hash heuristic. The choice is made by settings (VISION_ENABLED, VISION_PROVIDER);
see docs/VISION.md.

The learned model is loaded once per process and reused. A failed load is remembered, so a missing model is logged
once and never retried on every upload.
"""

import logging
from functools import lru_cache

from app.ai.providers.image import HeuristicImageEmbedder, ImageEmbedder
from app.ai.providers.text import HashingTextEmbedder, TextEmbedder, cosine
from app.core.config import get_settings

log = logging.getLogger("lostlink.vision")


@lru_cache(maxsize=1)
def _learned_embedder():
    """The ONNX embedder, or None when it cannot be used. Cached, so the model is loaded at most once."""
    from app.ai.providers.vision import OnnxVisionEmbedder, VisionUnavailable, default_model_path

    s = get_settings()
    try:
        embedder = OnnxVisionEmbedder.load(default_model_path(), s.vision_device)
        log.info("learned image embedder ready (device=%s)", embedder.device)
        return embedder
    except VisionUnavailable as exc:
        log.warning("learned image embedder unavailable, using the heuristic: %s", exc)
        return None


def get_text_embedder() -> TextEmbedder:
    return HashingTextEmbedder()


def get_image_embedder() -> ImageEmbedder:
    s = get_settings()
    if s.vision_enabled and s.vision_provider == "onnx":
        learned = _learned_embedder()
        if learned is not None:
            return learned
    return HeuristicImageEmbedder()


def image_method(embedder: ImageEmbedder) -> str:
    """Human-facing name of the visual method, used in evidence text and the stored record."""
    return "learned" if getattr(embedder, "name", "").startswith("onnx-") else "heuristic"


__all__ = ["TextEmbedder", "ImageEmbedder", "get_text_embedder", "get_image_embedder", "image_method", "cosine"]
