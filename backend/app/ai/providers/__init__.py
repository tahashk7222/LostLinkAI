"""Pluggable embedding providers.

To integrate an external/learned model (e.g. the vision team's CLIP service or an
OpenAI embedding model), implement the same interface and return it from
`get_text_embedder()` / `get_image_embedder()`.
"""

from app.ai.providers.image import HeuristicImageEmbedder, ImageEmbedder
from app.ai.providers.text import HashingTextEmbedder, TextEmbedder, cosine


def get_text_embedder() -> TextEmbedder:
    return HashingTextEmbedder()


def get_image_embedder() -> ImageEmbedder:
    return HeuristicImageEmbedder()


__all__ = ["TextEmbedder", "ImageEmbedder", "get_text_embedder", "get_image_embedder", "cosine"]
