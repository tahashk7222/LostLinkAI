"""Structured visual evidence for one lost/found pair, from the stored photo embeddings.

Aggregation (documented, and the only place it is decided):
- Compare every lost photo with every found photo, using the active embedder's similarity. Embeddings from a
  different model are never compared (similarity 0, and they are not counted).
- For each photo, take its best match on the other side. Then take the MEDIAN of those best matches over both sides.
- With one photo per side, that is the single pair similarity. With several photos, one accidental high match cannot
  set the result on its own: the median needs most photos to agree.

The result is evidence only. It never creates identity, and the matcher uses it only as corroboration (see
matching.py). No embedding or file path is returned, only numbers and labels.
"""

from statistics import median

from app.ai.providers import get_image_embedder, image_method


def visual_evidence(lost_images, found_images) -> dict:
    """Return {available, method, similarity, model, device, image_count, pairs_compared} or {available: False, reason}.

    Missing photos, missing embeddings, or embeddings that cannot be compared all give available=False with a reason.
    Nothing is fabricated: no similarity is reported unless at least one comparable pair exists.
    """
    lost = [i.embedding for i in lost_images if getattr(i, "embedding", None)]
    found = [i.embedding for i in found_images if getattr(i, "embedding", None)]
    if not lost or not found:
        return {"available": False, "reason": "no photos on one or both reports"}
    embedder = get_image_embedder()
    grid = [[embedder.similarity(a, b) for b in found] for a in lost]
    comparable = [(a, b) for a in range(len(lost)) for b in range(len(found))
                  if _comparable(lost[a], embedder.name) and _comparable(found[b], embedder.name)]
    if not comparable:
        return {"available": False, "reason": "stored photo embeddings come from a different model"}
    best_lost = [max(row) for row in grid]
    best_found = [max(grid[a][b] for a in range(len(lost))) for b in range(len(found))]
    similarity = median(best_lost + best_found)
    return {
        "available": True,
        "method": image_method(embedder),
        "similarity": round(float(similarity), 3),
        "model": embedder.name,
        "device": getattr(embedder, "device", "cpu"),
        "image_count": {"lost": len(lost), "found": len(found)},
        "pairs_compared": len(comparable),
    }


def _comparable(embedding: dict, model_name: str) -> bool:
    return isinstance(embedding, dict) and embedding.get("model") == model_name
