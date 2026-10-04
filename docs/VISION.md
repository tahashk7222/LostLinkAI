# Visual evidence: learned image embeddings (Computer Vision module)

This document describes the image model used for visual evidence in LostLink AI, how to install and configure it, and
what it can and cannot do. It is written so that a developer can use the module without reading every source file.

Visual evidence is **evidence only**. It never decides a lead, never notifies anyone, never creates a verification or a
case, and never establishes ownership. The existing matcher (`backend/app/ai/matching.py`) decides, using the same
identity, contradiction and notification rules as before. Embedding similarity is not a probability of ownership.

## 1. Model

| Item | Value |
|---|---|
| Model | MobileNetV2 v7, ImageNet pre-trained, from the ONNX Model Zoo |
| Source | `https://github.com/onnx/models/raw/main/validated/vision/classification/mobilenet/model/mobilenetv2-7.onnx` |
| Licence | Apache-2.0 (the ONNX Model Zoo MobileNet README states Apache 2.0) |
| Size | original 14.2 MB; the derived copy used at runtime is 14.2 MB |
| Runtime | onnxruntime 1.30.0 (CPU); CUDA is used only if onnxruntime-gpu is installed and `VISION_DEVICE` allows it |
| Embedding | global-average-pooled features, **1280 dimensions**, L2-normalised |
| Model name (stored) | `onnx-mobilenetv2-7-pool1280-v1` |

Why this model: it runs on a plain CPU in about 25 ms per image, it is small, its licence is permissive, and it loads
reproducibly from a checksum-verified file. A larger model such as CLIP would be stronger for semantic similarity, but it
would add several hundred MB of dependencies and be much slower on CPU. Reliability for the demo was the priority.

The weights are **not** committed to the repository (`backend/models/` is ignored by Git).

## 2. Installation

```powershell
cd backend
.\.venv\Scripts\pip install -r requirements.txt        # installs onnxruntime and numpy
.\.venv\Scripts\python -m scripts.fetch_vision_model   # downloads and verifies the model once
```

`fetch_vision_model` downloads the original file and checks its SHA-256. It then derives the runtime copy, which
exposes the 1280-d pooled features as an output, and checks that copy's SHA-256 too. The derivation uses the `onnx`
package, which is needed only by that script. The application does not import `onnx`.

Check an existing install: `python -m scripts.fetch_vision_model --check`.

## 3. Configuration (`backend/.env`)

| Variable | Default | Meaning |
|---|---|---|
| `VISION_ENABLED` | `true` | `false` disables the learned model entirely and uses the heuristic. |
| `VISION_PROVIDER` | `onnx` | `onnx` uses the learned model and falls back to the heuristic if it cannot load. `heuristic` uses the old method only. |
| `VISION_MODEL_PATH` | `models/vision/mobilenetv2-7-pooled.onnx` | Relative paths are resolved from the `backend/` folder. |
| `VISION_DEVICE` | `auto` | `auto` uses CUDA when available, otherwise CPU. `cpu` forces CPU. `cuda` uses CUDA only; if it is unavailable the heuristic is used. |

The model is loaded once per process and reused. A failed load is remembered, so a missing model is logged once and not
retried for every upload.

## 4. Pipeline

```
photo bytes
  → storage.save_image            (validation, size limit, EXIF orientation, alpha on white, re-encode as JPEG,
                                   metadata stripped; app/services/storage.py)
  → preprocess                    (RGB; shorter side 256; centre crop 224; ImageNet mean/std)   app/ai/providers/vision.py
  → model (ONNX, CPU or CUDA)     (1280-d pooled features)
  → L2 normalisation
  → ItemImage.embedding           (stored once, at upload; {"model", "dim", "device", "vec"})
  → visual_evidence(lost, found)  (median of best photo matches, both sides)                    app/ai/visual.py
  → score_pair                    (signals["image"], corroboration only; unchanged thresholds)  app/ai/matching.py
```

Preprocessing details:
- **Formats:** JPEG, PNG and WebP are accepted by the existing upload rules. Everything is stored as JPEG.
- **Orientation:** EXIF orientation is applied before metadata is dropped, so a rotated phone photo is stored upright.
- **Transparency:** transparent pixels are composited onto white, not left with arbitrary colours.
- **Corrupt or empty files** are refused with HTTP 400 at upload. A photo that cannot be embedded is stored without an
  embedding, and the report still works.
- **Privacy:** the stored photo is re-encoded, so EXIF and GPS are not kept. Tests check that a served photo has no
  metadata, and that embeddings and file paths never appear in any API response.

## 5. Multiple photos (aggregation)

Each lost photo is compared with each found photo. For each photo, the best match on the other side is taken. The
result is the **median** of those best matches over both sides.

- One photo per side: the result is that single pair's similarity.
- Several photos: one accidental high match cannot set the result, because the median needs most photos to agree.
  Tested in `tests/test_vision.py`.

Embeddings from a different model are never compared. A pair with no comparable embeddings gives `available: false` with
a reason, never a made-up score.

## 6. Similarity and output

Similarity is the cosine of the two normalised vectors. Pooled ReLU features are non-negative, so the cosine is already in
[0, 1]. It is not rescaled.

Structured visual evidence (`app/ai/visual.py::visual_evidence`):

```json
{"available": true, "method": "learned", "similarity": 0.91,
 "model": "onnx-mobilenetv2-7-pool1280-v1", "device": "cpu",
 "image_count": {"lost": 2, "found": 1}, "pairs_compared": 2}
```

When unavailable: `{"available": false, "reason": "..."}`. No embedding and no file path is ever in the output.

The matcher uses the value exactly as it used the old heuristic, with the same thresholds (`VISUAL_CORROBORATION = 0.7`,
and 0.55 for "somewhat similar"). The evidence text says "a learned visual model" or "colour and shape".

## 7. Fallback

| Situation | Behaviour |
|---|---|
| Model file missing, cannot load, onnxruntime missing | Logged once; the heuristic is used. |
| CUDA requested but unavailable | `VISION_DEVICE=auto` uses the CPU. `VISION_DEVICE=cuda` makes the learned model unavailable, so the heuristic is used (logged). |
| Inference error during upload | The photo is stored with no embedding; the upload still succeeds. |
| Corrupt or missing photo | Refused or treated as no photo; matching continues on the other signals. |
| Stored embeddings from another model | Not compared; visual evidence is reported unavailable. |
| `VISION_ENABLED=false` | The heuristic is used. |

Matching never crashes because of the visual module, and no score is invented when visual evidence is unavailable.

## 8. Caching

- The model session is a process-wide singleton (`functools.lru_cache`).
- Photo embeddings are computed once, at upload, and stored in `ItemImage.embedding` (JSON). No new table, no vector
  database, no migration.
- Embeddings are rebuildable from the stored photos. After the model is installed, run:

  ```powershell
  .\.venv\Scripts\python -m scripts.recompute_image_embeddings          # stale photos only
  .\.venv\Scripts\python -m scripts.recompute_image_embeddings --all    # every photo
  ```

  Unreadable or missing files are counted as failed and their old value is kept.

## 9. Service interface

There is no separate network service. The module is in-process, behind the existing provider functions:

- `app.ai.providers.get_image_embedder()`: returns the learned embedder or the heuristic. Methods: `embed(PIL.Image) -> dict`
  and `similarity(dict, dict) -> float`.
- `app.ai.providers.image_method(embedder) -> "learned" | "heuristic"`.
- `app.ai.visual.visual_evidence(lost_images, found_images) -> dict`: the structured evidence described in section 6.

An embedding is a dictionary `{"model": str, "dim": 1280, "device": "cpu" | "cuda", "vec": [1280 floats]}`. It is
internal. The API never returns it.

## 10. Tests

`backend/tests/test_vision.py` (33 tests, 1 skipped when CUDA is absent):

- preprocessing: shape, range, RGB/RGBA/L/P, transparency on white;
- formats: JPEG, PNG and WebP stored as JPEG; EXIF orientation applied; GPS and camera metadata not kept;
- corrupt, empty and missing photos;
- model: loads on CPU, dimension 1280, unit norm, deterministic, self-similarity 1.0, symmetry, bounded;
  CUDA only when available (skipped here);
- aggregation: one accidental match cannot set the result, consistent matches agree, single pair reported as is;
- different-model embeddings and malformed vectors are not compared;
- fallback: missing model, inference failure during upload, CV disabled, heuristic selected explicitly;
- integration: learned evidence reaches the matcher as corroboration; a visual match alone never notifies;
- privacy: embeddings absent from every API response; served photos carry no GPS metadata;
- recompute: stale embeddings replaced; missing files counted as failed, nothing deleted.

Existing tests were kept. Two photo-only tests now build their embeddings with the active embedder, because the old
heuristic embeddings are correctly no longer compared with the learned model.

## 11. Evaluation

`backend/evaluation/vision_eval.py` generates **synthetic drawn objects** (wallet, bag, phone, shoe, laptop, bottle,
headphones) with angle, lighting and background variants. Nothing is saved to the repository. Results are in
`backend/evaluation/results/vision-eval-v1.json`.

Cosine similarity, 12 pairs per group:

| Group | Learned model (min / median / max) | Heuristic (min / median / max) |
|---|---|---|
| Genuine (same object, angle or lighting changed) | 0.919 / 0.953 / 0.994 | 0.366 / 0.856 / 0.924 |
| Hard negatives (look-alike, different object) | 0.749 / 0.919 / 0.979 | 0.742 / 0.896 / 0.953 |
| Unrelated (different category) | 0.651 / 0.677 / 0.714 | 0.554 / 0.630 / 0.836 |

Overlap: with the learned model, no unrelated pair reaches the genuine median, and the unrelated maximum (0.714) is below
the genuine minimum (0.919). A quarter of the hard negatives reach the genuine median, because look-alike objects look
alike to any appearance model. The heuristic gives two-thirds overlap for hard negatives.

**Important calibration issue:** the learned scale is shifted. Unrelated pairs sit around 0.68, close to the existing
corroboration threshold of 0.7, so a few unrelated photo pairs may be described as "visually similar". This cannot
create a lead or a notification by itself, but it is a real limitation. The thresholds were not changed, because tuning
them on synthetic images would overfit. Calibrate on real photographs before any release.

## 11a. Unrelated-object findings (threshold NOT changed)

Three of the 12 unrelated pairs (`backend/evaluation/results/vision-eval-v1.json`, `unrelated_pairs`) reach the 0.7
corroboration threshold with the learned model:

| Pair | Learned similarity | Heuristic similarity | Reaches 0.7 |
|---|---|---|---|
| headphones vs bag (pair 3) | 0.714 | 0.554 | yes |
| phone vs bottle (pair 8) | 0.701 | 0.699 | yes |
| headphones vs bag (pair 11) | 0.714 | 0.564 | yes |

Effect on the existing matcher (run through the real `score_pair`, with the same timestamps and location):

- **Realistic case** (different categories, as in the dataset): the category gate applies. The pair gets no lead
  (`lead None`, relevance about 0.32 to 0.35) and does not notify.
- **Worst case** (same category, colour and place, no shared text or feature): relevance is 0.763 with the visual signal
  and 0.727 without it. The lead is **WEAK**, nothing notifies, and no identity group forms. The visual evidence adds
  about 0.04 to the relevance score and does not change any lead.

So no unrelated pair reaches Strong, Possible or notification in either configuration. The identity safeguards prevent
it: visual similarity is corroboration only, and the matcher requires an identity group before a visual match can count.

The threshold (0.7) and the weights were deliberately NOT changed on the basis of this synthetic set. Calibrate on real
photographs before any release.

## 12. Matching impact (regression)

The four matching evaluations were re-run with the learned model (`vision-ml-*.json`) and with the heuristic
(reproducing the recorded `final-*.json` exactly).

- Learned model: P@1, recall, false-positive rates, notification precision and notifications per query are unchanged on
  all four synthetic sets.
- Extended set: 10 of 50 true pairs changed their relevance score slightly (for example 0.705 to 0.721). Their leads did
  not change.
- Cases set: no true-pair score changed in this run, so the photos in that set did not move the scores.

## 13. Performance

Measured on this development laptop, CPU only (`vision-eval-v1.json`):

| Measure | Value |
|---|---|
| Model initialisation | about 0.19 to 0.39 s (once per process) |
| First inference | about 0.03 to 0.05 s |
| Subsequent inference (mean of 20) | about 0.03 s |
| CUDA | not measured: no CUDA execution provider is installed on this machine |

## 14. Security checks

- No EXIF or GPS metadata reaches a served photo (tested).
- No embedding is exposed in any API response (tested).
- No private file path is exposed in report responses (tested).
- No API keys or paid services are used. The model runs locally.
- Model weights, databases and user photos are not committed (`backend/models/`, `backend/storage/`, `backend/*.db`
  are ignored).

## 15. Limitations

- **Not a measure of real-world accuracy.** The evaluation uses drawn objects, not photographs. Real photographs are
  needed before any claim about accuracy.
- **Look-alike objects are not separated well.** ImageNet features respond to colour, texture and shape, so two black
  wallets look alike. Visual evidence therefore cannot tell identical-looking items apart.
- **Score scale.** Unrelated photos sit near the corroboration threshold (section 11). Calibration is needed.
- **No model-based colour or category extraction** is used in scoring. Colour and category still come from text rules.
- **CUDA** is supported in code but was not measured.
- **Migration of old photos:** photos uploaded before this change keep their heuristic embedding until recomputed, and
  they are not compared with the learned embeddings in the meantime.
- **Tests that need the model** are skipped if it is not installed, so run `scripts.fetch_vision_model` before relying
  on them.

## 16. Integration summary (for the team)

- **Computer Vision (this module):** `app/ai/providers/vision.py`, `app/ai/visual.py`, `scripts/fetch_vision_model.py`,
  `scripts/recompute_image_embeddings.py`, `evaluation/vision_eval.py`, `tests/test_vision.py`.
- **Matching (unchanged policy):** `app/ai/matching.py` uses `visual_evidence` where it used to compute the image signal.
- **Storage (one change):** `app/services/storage.py` applies EXIF orientation and composites transparency before it strips
  metadata.
- **Frontend:** no change. The learned-model evidence appears in the existing evidence list as text.
