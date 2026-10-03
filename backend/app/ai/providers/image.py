"""Local visual features: colour histogram + perceptual difference hash.

This measures overall colour distribution and coarse structure. It is a heuristic,
NOT object recognition, and is labelled as such in explanations. A learned vision
model can replace it by implementing `ImageEmbedder`.
"""

from typing import Protocol

from PIL import Image


class ImageEmbedder(Protocol):
    name: str

    def embed(self, img: Image.Image) -> dict: ...

    def similarity(self, a: dict, b: dict) -> float: ...


class HeuristicImageEmbedder:
    name = "color-dhash-v1"
    BINS = 4  # per channel -> 64-bin RGB histogram

    def embed(self, img: Image.Image) -> dict:
        img = img.convert("RGB")
        # Centre crop (items are usually centred; reduces background influence).
        w, h = img.size
        cw, ch = int(w * 0.8), int(h * 0.8)
        img = img.crop(((w - cw) // 2, (h - ch) // 2, (w + cw) // 2, (h + ch) // 2))

        small = img.resize((32, 32))
        hist = [0.0] * (self.BINS**3)
        step = 256 // self.BINS
        for r, g, b in small.getdata():
            hist[(r // step) * self.BINS * self.BINS + (g // step) * self.BINS + (b // step)] += 1
        total = sum(hist)
        hist = [round(v / total, 5) for v in hist]

        gray = img.convert("L").resize((9, 8))
        px = list(gray.getdata())
        bits = 0
        for row in range(8):
            for col in range(8):
                bits = (bits << 1) | (1 if px[row * 9 + col] > px[row * 9 + col + 1] else 0)
        return {"model": self.name, "hist": hist, "dhash": f"{bits:016x}"}

    def similarity(self, a: dict, b: dict) -> float:
        if not a or not b or a.get("model") != b.get("model"):
            return 0.0
        hist_sim = sum(min(x, y) for x, y in zip(a["hist"], b["hist"]))  # histogram intersection
        hamming = bin(int(a["dhash"], 16) ^ int(b["dhash"], 16)).count("1")
        hash_sim = 1 - hamming / 64
        return max(0.0, min(1.0, 0.65 * hist_sim + 0.35 * hash_sim))
