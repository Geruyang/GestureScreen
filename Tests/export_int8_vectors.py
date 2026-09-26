"""Freeze the exact original 50 numerical inputs; no training or hardware.

The PCG64 seed, shapes and creation order are copied from the already validated
Models/tests/compare_c_backend.py. Run using the existing model-training venv.
"""
import hashlib
import json
from pathlib import Path
import numpy as np

root = Path(__file__).resolve().parents[1]
rng = np.random.default_rng(20260915)
vectors = [np.full((1, 96, 96, 1), v, dtype=np.int8) for v in (-128, -1, 0, 1, 127)]
vectors += [np.arange(9216, dtype=np.int32).astype(np.int8).reshape(1, 96, 96, 1)]
vectors += [rng.integers(-128, 128, size=(1, 96, 96, 1), dtype=np.int8) for _ in range(44)]
data = b"".join(v.tobytes() for v in vectors)
path = root / "Tests/fixtures/int8_original_50.bin"
if path.exists() and path.read_bytes() != data:
    raise RuntimeError("Refusing to overwrite different frozen original vectors")
path.write_bytes(data)
path.with_suffix(".json").write_text(json.dumps(dict(
    scope="Original 50 numerical vectors; no gesture accuracy or MCU timing claim",
    source="Models/tests/compare_c_backend.py", seed=20260915, numpy=np.__version__,
    vector_count=len(vectors), bytes=len(data), sha256=hashlib.sha256(data).hexdigest()
), indent=2) + "\n", encoding="utf-8")
print(path)
