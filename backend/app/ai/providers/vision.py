"""Learned visual embeddings: MobileNetV2 (ImageNet) exported to ONNX, run locally with onnxruntime.

Pipeline: image -> preprocess (EXIF orientation, alpha on white, resize shorter side to 256, centre crop 224,
ImageNet normalisation) -> model -> 1280-d pooled features -> L2 normalisation.

Model: MobileNetV2 v7 from the ONNX Model Zoo (Apache-2.0). About 14 MB. CPU is enough; CUDA is used only when
onnxruntime's CUDA provider is installed and VISION_DEVICE allows it. The weights are NOT in the repository:
run `python -m scripts.fetch_vision_model` once (see docs/VISION.md).

This is visual evidence only. Embedding similarity is not a probability of ownership, and it never decides a lead
on its own. The matcher decides (see app/ai/visual.py and app/ai/matching.py).
"""

import logging
from pathlib import Path

import numpy as np
from PIL import Image

log = logging.getLogger("lostlink.vision")

MODEL_NAME = "onnx-mobilenetv2-7-pool1280-v1"
EMBED_DIM = 1280
INPUT_SIZE = 224
SHORT_SIDE = 256
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
INPUT_NAME = "data"
POOL_OUTPUT = "mobilenetv20_features_pool0_fwd"  # global-average-pooled features, shape (1, 1280, 1, 1)


class VisionUnavailable(Exception):
    """The learned model cannot be used on this machine. Callers fall back to the heuristic."""


def preprocess(img: Image.Image) -> np.ndarray:
    """Turn a decoded Pillow image into the model's input tensor, shape (1, 3, 224, 224), float32."""
    from PIL import ImageOps

    img = ImageOps.exif_transpose(img)  # EXIF orientation; the orientation tag is then ignored
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        img = background
    img = img.convert("RGB")
    w, h = img.size
    scale = SHORT_SIDE / min(w, h)
    img = img.resize((max(INPUT_SIZE, round(w * scale)), max(INPUT_SIZE, round(h * scale))), Image.BICUBIC)
    left, top = (img.width - INPUT_SIZE) // 2, (img.height - INPUT_SIZE) // 2
    img = img.crop((left, top, left + INPUT_SIZE, top + INPUT_SIZE))
    x = (np.asarray(img, dtype=np.float32) / 255.0 - MEAN) / STD
    return np.ascontiguousarray(x.transpose(2, 0, 1)[None], dtype=np.float32)


def l2_normalise(vec: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vec))
    if norm == 0.0:
        raise ValueError("zero-length embedding")
    return vec / norm


def default_model_path() -> Path:
    """Relative paths in settings are resolved from the backend folder, not from the current directory."""
    from app.core.config import get_settings

    raw = Path(get_settings().vision_model_path)
    return raw if raw.is_absolute() else Path(__file__).resolve().parents[3] / raw


class OnnxVisionEmbedder:
    name = MODEL_NAME

    def __init__(self, session, device: str) -> None:
        self._session = session
        self.device = device

    @classmethod
    def load(cls, model_path: Path, device: str = "auto") -> "OnnxVisionEmbedder":
        """Create an inference session. Raises VisionUnavailable with a reason if anything is missing or broken."""
        if not model_path.is_file():
            raise VisionUnavailable(f"model file not found at {model_path}; run scripts/fetch_vision_model.py")
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise VisionUnavailable("onnxruntime is not installed") from exc
        available = ort.get_available_providers()
        providers: list[str] = []
        if device in ("auto", "cuda") and "CUDAExecutionProvider" in available:
            providers.append("CUDAExecutionProvider")
        if device == "cuda" and "CUDAExecutionProvider" not in providers:
            raise VisionUnavailable("VISION_DEVICE=cuda but onnxruntime has no CUDA provider on this machine")
        providers.append("CPUExecutionProvider")
        try:
            session = ort.InferenceSession(str(model_path), providers=providers)
        except Exception as exc:  # corrupt file, unsupported op, provider failure
            raise VisionUnavailable(f"model could not be initialised: {exc.__class__.__name__}") from exc
        used = session.get_providers()[0]
        return cls(session, "cuda" if used == "CUDAExecutionProvider" else "cpu")

    def embed(self, img: Image.Image) -> dict:
        """Embedding of one image: {"model", "dim", "device", "vec"} with an L2-normalised vector."""
        x = preprocess(img)
        pooled = self._session.run([POOL_OUTPUT], {INPUT_NAME: x})[0]
        vec = l2_normalise(pooled.reshape(-1).astype(np.float64))
        if vec.shape[0] != EMBED_DIM:
            raise ValueError(f"unexpected embedding size {vec.shape[0]}")
        return {"model": self.name, "dim": EMBED_DIM, "device": self.device,
                "vec": [round(float(v), 6) for v in vec]}

    def similarity(self, a: dict, b: dict) -> float:
        """Cosine similarity in [0, 1]. Pooled ReLU features are non-negative, so cosine is already in that range.

        Embeddings from a different model (or with no vector) are not comparable and give 0.
        """
        if not a or not b or a.get("model") != self.name or b.get("model") != self.name:
            return 0.0
        va, vb = np.asarray(a.get("vec", []), dtype=np.float64), np.asarray(b.get("vec", []), dtype=np.float64)
        if va.shape != (EMBED_DIM,) or vb.shape != (EMBED_DIM,):
            return 0.0
        na, nb = float(np.linalg.norm(va)), float(np.linalg.norm(vb))
        if na == 0.0 or nb == 0.0:
            return 0.0
        return float(max(0.0, min(1.0, float(va @ vb) / (na * nb))))
