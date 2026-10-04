"""Download the learned image model once, and verify it.

    python -m scripts.fetch_vision_model            # writes backend/models/vision/mobilenetv2-7-pooled.onnx
    python -m scripts.fetch_vision_model --check    # only verify the existing derived file

Source: ONNX Model Zoo, MobileNetV2 v7 (Apache-2.0). The downloaded file is verified by SHA-256. It is then derived
once into a copy whose graph also exposes the global-average-pooled 1280-d features (the embedding), and that copy
is verified too. The derivation needs the `onnx` package, which is only used here; the runtime does not need it.
The weights are never committed to Git (backend/models/ is ignored).
"""

import argparse
import hashlib
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

from app.ai.providers.vision import default_model_path

URL = "https://github.com/onnx/models/raw/main/validated/vision/classification/mobilenet/model/mobilenetv2-7.onnx"
SHA256 = "c1c513582d56afceff8516c73804e484c81c6a830712ab6d682253f4a3cd042f"  # the downloaded original
DERIVED_SHA256 = "f64156f74a3a265bd5c024c896284b6b3e68371b7d2ff95da7cd7fc7e4cb5e04"  # the pooled-output copy
POOL_OUTPUT = "mobilenetv20_features_pool0_fwd"


def derive(raw: Path, out: Path) -> None:
    """Add the pooled 1280-d tensor as a graph output, so onnxruntime can return it as the embedding."""
    import onnx
    from onnx import TensorProto, helper

    model = onnx.load(str(raw))
    model.graph.output.append(helper.make_tensor_value_info(POOL_OUTPUT, TensorProto.FLOAT, [1, 1280, 1, 1]))
    onnx.save(model, str(out))


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="verify the existing file only")
    args = ap.parse_args()
    target = default_model_path()  # the derived, pooled-output model the embedder loads
    if target.is_file() and sha256_of(target) == DERIVED_SHA256:
        print(f"model already present and verified: {target}")
        return
    if args.check:
        print(f"model missing or does not match the expected checksum: {target}")
        sys.exit(1)
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = target.parent / "mobilenetv2-7.onnx"
    if not (raw.is_file() and sha256_of(raw) == SHA256):
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False, suffix=".part") as tmp:
            tmp_path = Path(tmp.name)
        try:
            print(f"downloading {URL}")
            urllib.request.urlretrieve(URL, tmp_path)
            digest = sha256_of(tmp_path)
            if digest != SHA256:
                raise SystemExit(f"checksum mismatch: expected {SHA256}, got {digest}. The file was not kept.")
            os.replace(tmp_path, raw)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()
    derived_tmp = target.with_suffix(".part.onnx")
    derive(raw, derived_tmp)
    digest = sha256_of(derived_tmp)
    if digest != DERIVED_SHA256:
        derived_tmp.unlink()
        raise SystemExit(f"derived model checksum mismatch: expected {DERIVED_SHA256}, got {digest}")
    os.replace(derived_tmp, target)
    print(f"saved and verified: {target} ({target.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
