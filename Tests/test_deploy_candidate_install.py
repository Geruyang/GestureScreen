"""Offline unit tests for candidate identity/instrumentation; no production writes."""
import importlib.util
import hashlib
import json
from pathlib import Path
import re
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "Tools/deploy_candidate_install.py"
SPEC = importlib.util.spec_from_file_location("candidate_install", TARGET)
MOD = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(MOD)


header_path = ROOT / "Middlewares/ST/AI/Generated/gs_network.h"
source_path = ROOT / "Middlewares/ST/AI/Generated/gs_network.c"
header = header_path.read_text(encoding="utf-8")
contract = MOD.parse_header_contract(header)
assert contract["input_size"] == 9216 and contract["input_scale"] == 1.0
assert contract["input_zero"] == -128 and contract["output_size"] == 7
assert contract["activation_bytes"] == 58624

# The real generated graph, with the existing hooks removed, must round-trip
# through the new candidate instrumenter byte-for-byte.
installed = source_path.read_text(encoding="utf-8")
plain = installed.replace('\n#include "gs_cubeai_backend.h"', '')
plain = re.sub(r'\n  if \(!gs_cubeai_layer_done\(\d+U, \d+U\)\) '
               r'\{ return STAI_ERROR_GENERIC; \}', '', plain)
assert "gs_cubeai_layer_done(" not in plain
assert MOD.instrument_source(plain) == installed

try:
    MOD.instrument_source(plain.replace("LITE_KERNEL_SECTION END conv2d_14",
                                        "LITE_KERNEL_SECTION END changed_14"))
    raise AssertionError("changed layer graph was accepted")
except ValueError as exc:
    assert "markers changed" in str(exc)

try:
    MOD.parse_header_contract(header.replace(
        "STAI_GS_NETWORK_ACTIVATIONS_SIZE_BYTES        (58624)",
        "STAI_GS_NETWORK_ACTIVATIONS_SIZE_BYTES        (65537)"))
    raise AssertionError("oversized CCM arena was accepted")
except ValueError as exc:
    assert "fixed seven-class/CCM" in str(exc)

try:
    MOD.parse_header_contract(header.replace(
        "STAI_GS_NETWORK_ACTIVATIONS_SIZE_BYTES        (58624)",
        "STAI_GS_NETWORK_ACTIVATIONS_SIZE_BYTES        (0)"))
    raise AssertionError("zero activation arena was accepted")
except ValueError as exc:
    assert "fixed seven-class/CCM" in str(exc)

backend = (ROOT / "Modules/StaticRecognition/Src/gs_cubeai_backend.c").read_text(encoding="utf-8")
updated = MOD.backend_for_signature(backend, "0x0123456789abcdef")
assert "UINT64_C(0x0123456789abcdef)" in updated
assert updated.count("GS_APPROVED_MODEL_SIGNATURE") == backend.count("GS_APPROVED_MODEL_SIGNATURE")

with tempfile.TemporaryDirectory() as directory:
    tflite = Path(directory) / "model.tflite"; tflite.write_bytes(b"fixed-candidate")
    registry = {"winner_best_weights_sha256": "w", "dataset_manifest_sha256": "d",
                "winner_saved_model_pb_sha256": "p"}
    valid = {"model_sha256": MOD.sha(tflite), "weights_sha256": "w",
             "saved_model_pb_sha256": "p",
             "dataset_manifest_sha256": "d", "input_shape": [1,96,96,1],
             "input_scale": 1.0, "input_zero": -128, "output_shape": [1,7],
             "output_scale": 0.125, "output_zero": -3, "labels": MOD.LABELS}
    MOD.check_conversion(valid, registry, tflite)
    invalid = dict(valid); invalid["labels"] = list(reversed(MOD.LABELS))
    try:
        MOD.check_conversion(invalid, registry, tflite)
        raise AssertionError("changed label order was accepted")
    except ValueError as exc:
        assert "labels" in str(exc)
    invalid = dict(valid); invalid["output_scale"] = float("nan")
    try:
        MOD.check_conversion(invalid, registry, tflite)
        raise AssertionError("non-finite output scale was accepted")
    except ValueError as exc:
        assert "quantization" in str(exc)

# The bounded installer must reject baseline drift and must restore every file
# after a failure between atomic per-file replacements.
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    targets = [root / "a.bin", root / "b.bin", root / "c.bin"]
    for index, target in enumerate(targets):
        target.write_bytes(f"old-{index}".encode())
    before = {target: MOD.sha(target) for target in targets}
    payloads = {target: f"new-{index}".encode() for index, target in enumerate(targets)}
    receipt = root / "receipt.json"
    try:
        MOD.transactional_replace(payloads, before, receipt, "1" * 64, fail_after=2)
        raise AssertionError("injected partial install did not fail")
    except RuntimeError as exc:
        assert "injected" in str(exc)
    assert all(MOD.sha(target) == before[target] for target in targets)
    failed = json.loads(receipt.read_text(encoding="utf-8"))
    assert failed["state"] == "failed" and failed["production_restored"] is True
    result = MOD.transactional_replace(payloads, before, receipt, "2" * 64)
    assert result["state"] == "installed"
    assert all(target.read_bytes() == payloads[target] for target in targets)
    drift = dict(before); drift[targets[0]] = hashlib.sha256(b"wrong").hexdigest()
    try:
        MOD.transactional_replace(payloads, drift, receipt, "3" * 64)
        raise AssertionError("baseline drift was accepted")
    except ValueError as exc:
        assert "baseline mismatch" in str(exc)

identity = {"contract": contract, "labels": MOD.LABELS}
digest = MOD.canonical_sha(identity)
assert digest == MOD.canonical_sha(json.loads(json.dumps(identity)))
MOD.check_generate_report("generate --model gesture_v7_int8.tflite --target stm32f4 "
    "--name gs_network --compression none --optimization time --no-inputs-allocation "
    "--no-outputs-allocation --c-api st-ai")
try:
    MOD.check_generate_report("generate --model gesture_v7_int8.tflite --target stm32f4")
    raise AssertionError("incomplete official generation options were accepted")
except ValueError as exc:
    assert "fixed options" in str(exc)
print("PASS: candidate contract, 29-hook round-trip, CCM bound, model signature and label identity")
