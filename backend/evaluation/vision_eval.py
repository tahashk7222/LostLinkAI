"""Controlled evaluation of the visual evidence (SYNTHETIC images only).

The images are procedurally drawn objects (wallet, bag, phone, shoe, laptop, bottle, headphones). Genuine pairs are the
same object with a different angle, lighting or background. Hard negatives are different objects built to look alike
(different black wallets, same logo on a different wallet, same colour on a different bag, similar shapes with
different patterns). Unrelated pairs are different categories.

These images are NOT photographs, so the numbers do not measure real-world accuracy. They show how the two visual
methods separate the three groups on this controlled set. Nothing is saved to the repository: the images are
generated into a temporary folder and discarded.

    python -m evaluation.vision_eval --label vision-eval-v1
"""

import argparse
import json
import math
import random
import statistics
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance

from app.ai.providers import get_image_embedder
from app.ai.providers.image import HeuristicImageEmbedder
from app.ai.providers.vision import OnnxVisionEmbedder, default_model_path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
W, H = 320, 240


def _draw(kind: str, color: tuple, bg: tuple, seed: int) -> Image.Image:
    rng = random.Random(seed)
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    if kind == "wallet":
        d.rounded_rectangle((60, 90, 260, 170), radius=16, fill=color)
        for k in range(rng.randint(2, 5)):  # pattern: stripes whose count depends on the seed
            x = 80 + k * (160 // max(1, rng.randint(3, 6)))
            d.line((x, 100, x, 160), fill=tuple(max(0, c - 60) for c in color), width=3)
        d.ellipse((230, 118, 246, 134), fill=(220, 220, 220))
    elif kind == "bag":
        d.rounded_rectangle((90, 50, 230, 230), radius=28, fill=color)
        d.rounded_rectangle((115, 150, 205, 210), radius=10, fill=tuple(max(0, c - 40) for c in color))
        d.line((120, 60, 120, 140), fill=(30, 30, 30), width=5)
        d.line((200, 60, 200, 140), fill=(30, 30, 30), width=5)
        for k in range(rng.randint(1, 3)):
            d.line((100 + 40 * k, 160, 100 + 40 * k, 180), fill=(230, 230, 230), width=2)
    elif kind == "phone":
        d.rounded_rectangle((115, 30, 205, 210), radius=14, fill=color)
        d.rectangle((125, 45, 195, 185), fill=(40, 40, 60))
        for k in range(rng.randint(1, 4)):
            d.rectangle((130 + 15 * k, 190, 140 + 15 * k, 200), fill=(200, 200, 200))
    elif kind == "shoe":
        d.polygon([(60, 170), (60, 110), (150, 90), (230, 120), (250, 170)], fill=color)
        d.rectangle((60, 165, 255, 185), fill=tuple(max(0, c - 70) for c in color))
        for k in range(rng.randint(2, 4)):
            d.line((110 + 25 * k, 110, 120 + 25 * k, 135), fill=(240, 240, 240), width=3)
    elif kind == "laptop":
        d.rectangle((70, 60, 250, 150), fill=color)
        d.rectangle((84, 74, 236, 138), fill=(30, 40, 60))
        d.rectangle((40, 150, 280, 172), fill=tuple(min(255, c + 30) for c in color))
    elif kind == "bottle":
        d.rectangle((140, 20, 180, 60), fill=(40, 40, 40))
        d.polygon([(130, 60), (190, 60), (200, 110), (200, 220), (120, 220), (120, 110)], fill=color)
        d.rectangle((120, 150, 200, 180), fill=(240, 240, 240))
    elif kind == "headphones":
        d.arc((90, 30, 230, 170), start=180, end=360, fill=color, width=14)
        d.rounded_rectangle((80, 110, 120, 190), radius=12, fill=color)
        d.rounded_rectangle((200, 110, 240, 190), radius=12, fill=color)
    return img


def _augment(img: Image.Image, rng: random.Random, angle: bool, light: bool) -> Image.Image:
    out = img
    if angle:
        out = out.rotate(rng.uniform(-9, 9), resample=Image.BICUBIC, fillcolor=out.getpixel((2, 2)))
        shear = rng.uniform(-0.12, 0.12)
        out = out.transform(out.size, Image.AFFINE, (1, shear, 0, 0, 1, 0), resample=Image.BICUBIC,
                            fillcolor=out.getpixel((2, 2)))
    if light:
        out = ImageEnhance.Brightness(out).enhance(rng.uniform(0.75, 1.25))
        out = ImageEnhance.Contrast(out).enhance(rng.uniform(0.8, 1.2))
        r, g, b = out.split()
        out = Image.merge("RGB", (r.point(lambda v: min(255, int(v * rng.uniform(0.9, 1.1)))), g,
                                  b.point(lambda v: min(255, int(v * rng.uniform(0.9, 1.1))))))
    return out


BACKGROUNDS = [(235, 235, 235), (200, 215, 230), (90, 110, 80), (180, 160, 140)]


UNRELATED_LABELS: list[str] = []  # filled by build_pairs, same order as groups['unrelated']


def build_pairs(seed: int = 7) -> dict[str, list[tuple[Image.Image, Image.Image]]]:
    rng = random.Random(seed)
    groups: dict[str, list[tuple[Image.Image, Image.Image]]] = {"genuine": [], "hard": [], "unrelated": []}
    palette = [(20, 20, 20), (120, 70, 35), (40, 60, 150), (150, 30, 30), (90, 150, 90)]
    for k, kind in enumerate(["wallet", "bag", "phone", "shoe"] * 3):
        colour = palette[k % len(palette)]
        base = _draw(kind, colour, BACKGROUNDS[0], seed=100 + k)
        if k % 2 == 0:  # different angle
            other = _augment(base, rng, angle=True, light=False)
        else:  # different lighting and background
            other = _augment(_draw(kind, colour, BACKGROUNDS[(k + 1) % len(BACKGROUNDS)], seed=100 + k), rng,
                             angle=False, light=True)
        groups["genuine"].append((base, other))
    # hard negatives: look-alike items that are different objects
    for k in range(12):
        colour = palette[k % len(palette)]
        if k % 3 == 0:  # two different black wallets
            a, b = _draw("wallet", (20, 20, 20), BACKGROUNDS[0], seed=300 + k), _draw("wallet", (20, 20, 20), BACKGROUNDS[0], seed=900 + k)
        elif k % 3 == 1:  # same colour, different category (bag vs wallet)
            a, b = _draw("wallet", colour, BACKGROUNDS[0], seed=400 + k), _draw("bag", colour, BACKGROUNDS[0], seed=500 + k)
        else:  # similar shape, different pattern
            a, b = _draw("shoe", colour, BACKGROUNDS[0], seed=600 + k), _draw("shoe", colour, BACKGROUNDS[0], seed=700 + k)
        groups["hard"].append((_augment(a, rng, angle=True, light=False), b))
    # unrelated: different categories
    pairs = [("wallet", "laptop"), ("bottle", "shoe"), ("headphones", "bag"), ("phone", "bottle")]
    for k in range(12):
        x, y = pairs[k % len(pairs)]
        UNRELATED_LABELS.append(f"{x} vs {y} (pair {k + 1})")
        groups["unrelated"].append((_draw(x, palette[k % 5], BACKGROUNDS[0], seed=800 + k),
                                    _draw(y, palette[(k + 2) % 5], BACKGROUNDS[1], seed=850 + k)))
    return groups


def _stats(values: list[float]) -> dict:
    return {"n": len(values), "min": round(min(values), 3), "max": round(max(values), 3),
            "mean": round(statistics.fmean(values), 3), "median": round(statistics.median(values), 3)}


def _overlap(genuine: list[float], other: list[float]) -> float:
    """Share of the other group's scores that reach the genuine median (how often a non-match looks as strong)."""
    cut = statistics.median(genuine)
    return round(sum(v >= cut for v in other) / len(other), 3)


def unrelated_detail(groups: dict, embedder, heuristic: HeuristicImageEmbedder) -> list[dict]:
    """Per-pair scores for the unrelated group: the object pair, both similarities, and whether either reaches 0.7."""
    rows = []
    for label, (a, b) in zip(UNRELATED_LABELS, groups["unrelated"]):
        learned = embedder.similarity(embedder.embed(a), embedder.embed(b))
        heur = heuristic.similarity(heuristic.embed(a), heuristic.embed(b))
        rows.append({"pair": label, "learned_similarity": round(learned, 3), "heuristic_similarity": round(heur, 3),
                     "learned_reaches_0_7": learned >= 0.7})
    return rows


def evaluate(groups: dict, embedder, heuristic: HeuristicImageEmbedder) -> dict:
    out = {}
    for name, method in (("learned", embedder), ("heuristic", heuristic)):
        scores = {}
        for group, pairs in groups.items():
            vals = []
            for a, b in pairs:
                ea, eb = method.embed(a), method.embed(b)
                vals.append(method.similarity(ea, eb))
            scores[group] = vals
        out[name] = {
            "genuine": _stats(scores["genuine"]), "hard": _stats(scores["hard"]),
            "unrelated": _stats(scores["unrelated"]),
            "overlap_hard_reaches_genuine_median": _overlap(scores["genuine"], scores["hard"]),
            "overlap_unrelated_reaches_genuine_median": _overlap(scores["genuine"], scores["unrelated"]),
        }
    return out


def performance(embedder, sample: Image.Image) -> dict:
    t0 = time.perf_counter()
    onnx = OnnxVisionEmbedder.load(default_model_path(), "cpu")
    init = time.perf_counter() - t0
    t0 = time.perf_counter()
    onnx.embed(sample)
    first = time.perf_counter() - t0
    t0 = time.perf_counter()
    for _ in range(20):
        onnx.embed(sample)
    subsequent = (time.perf_counter() - t0) / 20
    return {"device": "cpu", "cuda_available": _cuda_available(), "initialisation_s": round(init, 3),
            "first_inference_s": round(first, 4), "subsequent_inference_s_mean_of_20": round(subsequent, 4),
            "embedding_dim": onnx.embed(sample)["dim"], "active_provider_for_app": getattr(embedder, "device", "cpu")}


def _cuda_available() -> bool:
    import onnxruntime as ort

    return "CUDAExecutionProvider" in ort.get_available_providers()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", default="vision-eval-v1")
    args = ap.parse_args()
    groups = build_pairs()
    embedder = OnnxVisionEmbedder.load(default_model_path(), "cpu")
    result = {
        "label": args.label,
        "dataset": "SYNTHETIC procedurally drawn objects with angle, lighting and background variants",
        "counts": {k: len(v) for k, v in groups.items()},
        "model": embedder.name, "embedding_dim": 1280, "preprocessing": "EXIF orientation, RGB, shorter side 256, "
        "centre crop 224, ImageNet normalisation, L2 normalisation",
        "similarity": "cosine (pooled ReLU features are non-negative, so the range is [0, 1])",
        "scores": evaluate(groups, embedder, HeuristicImageEmbedder()),
        "unrelated_pairs": unrelated_detail(groups, embedder, HeuristicImageEmbedder()),
        "performance": performance(embedder, groups["genuine"][0][0]),
        "limits": ["Synthetic drawn objects, not photographs; small sample; no real-world accuracy claim."],
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"{args.label}.json"
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["scores"], indent=2))
    print(json.dumps(result["performance"], indent=2))
    print("wrote", out)


if __name__ == "__main__":
    main()
