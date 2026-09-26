"""Frozen v12 six-class RGB565 model for local observation only.

``qualified`` denotes one fresh, quality-accepted target frame that clears the
unchanged 0.90 score and 0.20 margin gates. It is not the firmware's temporal
gesture confirmation or a navigation command. The service owns frame freshness.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
from pathlib import Path
import threading

import numpy as np


_ASSET_DIR = Path(__file__).resolve().parent / "model"
_EXPECTED_MODEL_SHA256 = "9cc300884c79aed938dba492c7e5b536a1ab064b5f59c14d40c3628b7b7e4f4f"
_EXPECTED_FILES_SHA256 = {
    "gesture_v12_int8.tflite": _EXPECTED_MODEL_SHA256,
    "preprocess.dll": "9766c8a8897c639f63b9808e68b7f22876a970eb54f936c3aa94bd11bd1d75d1",
    "gs_preprocess.c": "60311398ccc43a19f6aada58b1aec3dfbd52a9430f45ce78bb1568147007d1dc",
    "gs_preprocess.h": "ac072193b6788b09b82e134bcc88643f2622713e6cd94e2051737a33d9aab70e",
    "preprocess_bridge.c": "a2f9aefc61d23839df9d7896261e3b1400a5c3d3b137b187dbcb84e16b170bb8",
}
_EXPECTED_WEIGHT_SHA256 = "72db45f37036530652ef07e19ad20e6ce94552027d0fc81a9987c074f6c5c4be"
_EXPECTED_BOARD_WEIGHT_SOURCE_SHA256 = "5021039d6f330e2ac29bdea22ae61c5ca2370a1a03e912a2efccb04b571ef0a6"
_CLASSES = ("POINT_LEFT", "POINT_RIGHT", "FIST", "PALM", "V_SIGN", "UNKNOWN")
_LABELS = ("指向左侧", "指向右侧", "握拳", "张开手掌", "V字手势")
_INPUT_SHAPE = (1, 96, 96, 3)
_OUTPUT_SHAPE = (1, 6)
_FRAME_BYTES = 320 * 240 * 2
_PREPROCESS_BAD_QUALITY = 4


class ModelContractError(RuntimeError):
    """Frozen model, preprocessing, or LiteRT tensor contract was changed."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check_tensor(details: dict, *, shape: tuple[int, ...], scale: float, zero_point: int) -> None:
    if tuple(int(x) for x in details["shape"]) != shape or details["dtype"] != np.int8:
        raise ModelContractError(f"unexpected tensor shape/dtype: {details['shape']}, {details['dtype']}")
    got_scale, got_zero = details["quantization"]
    if abs(float(got_scale) - scale) > 1e-8 or int(got_zero) != zero_point:
        raise ModelContractError(f"unexpected tensor quantization: {(got_scale, got_zero)}")
    if len(details.get("quantization_parameters", {}).get("scales", [])) != 1:
        raise ModelContractError("per-axis tensor quantization is not supported by this frozen contract")


class GestureModel:
    """One LiteRT interpreter with a locked synchronous inference interface."""

    def __init__(self, asset_dir: Path | str | None = None):
        self.asset_dir = Path(asset_dir).resolve() if asset_dir is not None else _ASSET_DIR
        manifest_path = self.asset_dir / "manifest.json"
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = self.manifest
        if (manifest.get("schema_version") != 1
                or manifest.get("source_weight_sha256") != _EXPECTED_WEIGHT_SHA256
                or manifest.get("board_generated_weight_source_sha256") != _EXPECTED_BOARD_WEIGHT_SOURCE_SHA256
                or manifest.get("classes") != list(_CLASSES)
                or manifest.get("preprocess_version") != "rgb565-roi192-rgb96-box2-v1"
                or manifest.get("frame_format") != "RGB565_BE"
                or manifest.get("frame_shape") != [240, 320, 2]
                or manifest.get("input_shape") != list(_INPUT_SHAPE)
                or manifest.get("output_shape") != list(_OUTPUT_SHAPE)
                or manifest.get("input_dtype") != "int8"
                or manifest.get("output_dtype") != "int8"
                or manifest.get("output_kind") != "logits"
                or manifest.get("input_scale") != 1.0
                or manifest.get("input_zero_point") != -128
                or abs(float(manifest.get("output_scale", 0)) - 0.09457084536552429) > 1e-8
                or manifest.get("output_zero_point") != -31
                or manifest.get("single_frame_target_score") != 0.9
                or manifest.get("single_frame_target_margin") != 0.2
                or manifest.get("neutral_score") != 0.95):
            raise ModelContractError("manifest differs from the frozen v12 six-class contract")
        expected = manifest.get("files_sha256")
        if expected != _EXPECTED_FILES_SHA256:
            raise ModelContractError("manifest asset hashes differ from frozen v12 inventory")
        for name, digest in expected.items():
            if _sha256(self.asset_dir / name) != digest:
                raise ModelContractError(f"model asset SHA-256 mismatch: {name}")

        from ai_edge_litert.interpreter import Interpreter, OpResolverType

        self._interpreter = Interpreter(model_path=str(self.asset_dir / "gesture_v12_int8.tflite"),
                                        num_threads=1,
                                        experimental_op_resolver_type=OpResolverType.BUILTIN_REF)
        self._interpreter.allocate_tensors()
        inputs = self._interpreter.get_input_details()
        outputs = self._interpreter.get_output_details()
        if len(inputs) != 1 or len(outputs) != 1:
            raise ModelContractError("expected one input and one output")
        _check_tensor(inputs[0], shape=_INPUT_SHAPE, scale=1.0, zero_point=-128)
        _check_tensor(outputs[0], shape=_OUTPUT_SHAPE,
                      scale=manifest["output_scale"], zero_point=-31)
        self._input_index = int(inputs[0]["index"])
        self._output_index = int(outputs[0]["index"])
        self._output_scale = np.float32(outputs[0]["quantization"][0])
        self._target_score = np.float32(manifest["single_frame_target_score"])
        self._target_margin = np.float32(manifest["single_frame_target_margin"])

        self._preprocess = ctypes.CDLL(str(self.asset_dir / "preprocess.dll")).check_frame
        self._preprocess.argtypes = (ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
                                     ctypes.c_int, ctypes.c_void_p)
        self._preprocess.restype = ctypes.c_int
        self._lock = threading.Lock()

    @property
    def identity(self) -> dict:
        """Stable public identity for the application's About display."""
        return {"model_id": self.manifest["model_id"],
                "model_sha256": _EXPECTED_MODEL_SHA256,
                "source_weight_sha256": _EXPECTED_WEIGHT_SHA256,
                "board_generated_weight_source_sha256": _EXPECTED_BOARD_WEIGHT_SOURCE_SHA256,
                "preprocess_version": self.manifest["preprocess_version"],
                "classes": list(_CLASSES)}

    def _infer_tensor(self, tensor: np.ndarray, frame_id: int) -> dict:
        """Exact quantized-input path shared by predict and frozen-vector audit."""
        if tensor.shape != _INPUT_SHAPE or tensor.dtype != np.int8:
            raise ModelContractError("quantized input is not NHWC 1x96x96x3 int8")
        self._interpreter.set_tensor(self._input_index, tensor)
        self._interpreter.invoke()
        logits = self._interpreter.get_tensor(self._output_index)
        if logits.shape != _OUTPUT_SHAPE or logits.dtype != np.int8:
            raise ModelContractError("LiteRT output changed shape or dtype")
        # Match gs_static_decode_logits: subtract max before float32 expf.
        shifted = (logits.reshape(6).astype(np.float32) -
                   np.float32(logits.max())) * self._output_scale
        values = np.exp(shifted).astype(np.float32)
        total = np.sum(values, dtype=np.float32)
        if not np.isfinite(total) or total <= 0:
            raise ModelContractError("invalid LiteRT logits")
        scores = values / total
        index = int(np.argmax(scores))
        confidence = float(scores[index])
        margin = float(scores[index] - np.max(np.delete(scores, index)))
        qualified = bool(index < 5 and scores[index] >= self._target_score
                         and np.float32(margin) >= self._target_margin)
        return {"frame_id": frame_id, "class_index": index, "class_name": _CLASSES[index],
                "label": _LABELS[index] if qualified else None,
                "confidence": confidence, "margin": margin,
                "qualified": qualified, "quality_ok": True}

    def predict(self, raw_rgb565: bytes, frame_id: int) -> dict:
        """Return one-frame classification; UNKNOWN and unqualified labels stay hidden.

        The caller must still enforce device epoch, frame order, and freshness.
        No temporal confirmation or UI action is generated here.
        """
        if not isinstance(frame_id, int) or isinstance(frame_id, bool) or not 0 <= frame_id <= 0xFFFFFFFF:
            raise ValueError("frame_id must be an unsigned 32-bit integer")
        if not isinstance(raw_rgb565, bytes) or len(raw_rgb565) != _FRAME_BYTES:
            raise ValueError(f"RGB565_BE frame must be exactly {_FRAME_BYTES} bytes")
        source = ctypes.create_string_buffer(raw_rgb565)
        tensor = np.empty(_INPUT_SHAPE, dtype=np.int8)
        with self._lock:
            status = self._preprocess(source, len(raw_rgb565), 640, 0,
                                      tensor.ctypes.data)
            if status == _PREPROCESS_BAD_QUALITY:
                return {"frame_id": frame_id, "class_index": None, "class_name": None,
                        "label": None, "confidence": None, "margin": None,
                        "qualified": False, "quality_ok": False}
            if status != 0:
                raise ModelContractError(f"RGB565 preprocessing failed: {status}")
            return self._infer_tensor(tensor, frame_id)
