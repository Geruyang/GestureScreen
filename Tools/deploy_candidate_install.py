"""Inspect/instrument a Cube.AI candidate; install only with an approved identity.

The default mode writes only beneath the candidate work directory.  It never
changes the production Generated directory or backend.  ``--install`` requires
an independently supplied approval JSON binding the complete candidate identity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORK = ROOT / "Build/deployment-new-model-20260920"
BASELINE = ROOT / "Build/timing-fix-20260920/release7/source"
REGISTRY = ROOT.parent / "custom_dataset/model_releases/LATEST_TRAINING_CANDIDATE.json"
LABELS = ["POINT_LEFT", "POINT_RIGHT", "FIST", "PALM", "V_SIGN", "OTHER", "EMPTY"]
LAYER_NAMES = [f"conv2d_{index}" for index in range(27)] + ["pool_27", "conv2d_28"]
GENERATED_MARKERS = ["conv2d_0"]
for _index in range(1, 27):
    if _index & 1:
        GENERATED_MARKERS.append(f"conv2d_{_index}_pad_before")
    GENERATED_MARKERS.append(f"conv2d_{_index}")
GENERATED_MARKERS += ["pool_27", "conv2d_28"]
LAYER_OUTPUTS = [18432,18432,36864,9216,18432,18432,18432,4608,9216,9216,
    9216,2304,4608,4608,4608,4608,4608,4608,4608,4608,4608,4608,4608,
    1152,2304,2304,2304,256,7]
GENERATED_FILES = ["gs_network.c", "gs_network.h", "gs_network_data.c",
                   "gs_network_data.h", "gs_network_details.h"]
GENERATED_EVIDENCE = ["gs_network_c_info.json", "gs_network_generate_report.txt", "LICENSE.txt"]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def macro_text(header: str, name: str) -> str:
    match = re.search(r"^#define\s+" + re.escape(name) + r"\s+(.+?)\s*$", header, re.M)
    if not match:
        raise ValueError(f"missing generated macro {name}")
    return match.group(1).strip()


def macro_int(header: str, name: str) -> int:
    expression = macro_text(header, name).replace("U", "").strip()
    if not re.fullmatch(r"[0-9xXa-fA-F()+*\-\s]+", expression):
        raise ValueError(f"unsafe/nonconstant integer macro {name}: {expression}")
    return int(eval(expression, {"__builtins__": {}}, {}))


def macro_float(header: str, name: str) -> float:
    expression = macro_text(header, name).strip().strip("()").rstrip("fF")
    return float(expression)


def macro_string(header: str, name: str) -> str:
    expression = macro_text(header, name)
    match = re.fullmatch(r'"([^"]+)"', expression)
    if not match:
        raise ValueError(f"expected string macro {name}: {expression}")
    return match.group(1)


def parse_header_contract(header: str) -> dict:
    contract = {
        "origin_model_name": macro_string(header, "STAI_GS_NETWORK_ORIGIN_MODEL_NAME"),
        "origin_model_signature": macro_string(header, "STAI_GS_NETWORK_ORIGIN_MODEL_SIGNATURE"),
        "model_signature": f"0x{macro_int(header, 'STAI_GS_NETWORK_MODEL_SIGNATURE'):016x}",
        "input_count": macro_int(header, "STAI_GS_NETWORK_IN_NUM"),
        "input_size": macro_int(header, "STAI_GS_NETWORK_IN_1_SIZE"),
        "input_format": macro_text(header, "STAI_GS_NETWORK_IN_1_FORMAT"),
        "input_scale": macro_float(header, "STAI_GS_NETWORK_IN_1_SCALE"),
        "input_zero": macro_int(header, "STAI_GS_NETWORK_IN_1_ZERO_POINT"),
        "output_count": macro_int(header, "STAI_GS_NETWORK_OUT_NUM"),
        "output_size": macro_int(header, "STAI_GS_NETWORK_OUT_1_SIZE"),
        "output_size_bytes": macro_int(header, "STAI_GS_NETWORK_OUT_SIZE_BYTES"),
        "output_format": macro_text(header, "STAI_GS_NETWORK_OUT_1_FORMAT"),
        "output_scale": macro_float(header, "STAI_GS_NETWORK_OUT_1_SCALE"),
        "output_zero": macro_int(header, "STAI_GS_NETWORK_OUT_1_ZERO_POINT"),
        "activation_bytes": macro_int(header, "STAI_GS_NETWORK_ACTIVATIONS_SIZE_BYTES"),
        "context_size_expression": macro_text(header, "STAI_GS_NETWORK_CONTEXT_SIZE"),
        "context_alignment": macro_int(header, "STAI_GS_NETWORK_CONTEXT_ALIGNMENT"),
        "input_alignment": macro_int(header, "STAI_GS_NETWORK_IN_1_ALIGNMENT"),
        "output_alignment": macro_int(header, "STAI_GS_NETWORK_OUT_1_ALIGNMENT"),
        "activation_alignment": macro_int(header, "STAI_GS_NETWORK_ACTIVATION_1_ALIGNMENT"),
    }
    alignments = [contract[name] for name in ("context_alignment", "input_alignment",
                                                "output_alignment", "activation_alignment")]
    if not (contract["input_count"] == contract["output_count"] == 1 and
            contract["input_size"] == 9216 and contract["input_format"] == "(STAI_FORMAT_S8)" and
            contract["input_scale"] == 1.0 and contract["input_zero"] == -128 and
            contract["output_size"] == 7 and contract["output_format"] == "(STAI_FORMAT_S8)" and
            contract["output_size_bytes"] >= 7 and math.isfinite(contract["output_scale"]) and
            contract["output_scale"] > 0.0 and -128 <= contract["output_zero"] <= 127 and
            0 < contract["activation_bytes"] <= 65536 and
            contract["context_size_expression"] == "(sizeof(_stai_gs_network_context))" and
            all(value > 0 and (value & (value - 1)) == 0 for value in alignments)):
        raise ValueError("candidate violates the fixed seven-class/CCM firmware contract")
    return contract


def check_conversion(meta: dict, registry: dict, tflite: Path) -> None:
    expected = {
        "weights_sha256": registry["winner_best_weights_sha256"],
        "dataset_manifest_sha256": registry["dataset_manifest_sha256"],
        "saved_model_pb_sha256": registry["winner_saved_model_pb_sha256"],
        "input_shape": [1, 96, 96, 1], "input_scale": 1.0, "input_zero": -128,
        "output_shape": [1, 7], "labels": LABELS,
    }
    for key, value in expected.items():
        if meta.get(key) != value:
            raise ValueError(f"conversion {key} does not match selected v7 contract")
    if meta.get("model_sha256") != sha(tflite):
        raise ValueError("conversion model_sha256 does not match gesture_v7_int8.tflite")
    output_scale = float(meta.get("output_scale", 0.0))
    if not math.isfinite(output_scale) or output_scale <= 0.0 or \
            not -128 <= int(meta.get("output_zero", 999)) <= 127:
        raise ValueError("invalid conversion output quantization")


def check_source_provenance(work: Path, conversion: dict, registry: dict,
                            provenance_path: Path, provenance: dict) -> None:
    files = provenance.get("files_sha256")
    if not isinstance(files, dict) or not files:
        raise ValueError("source-model provenance has no immutable file inventory")
    source_root = provenance_path.parent
    for relative, expected_sha in files.items():
        path = source_root / relative
        if not path.is_file() or sha(path) != expected_sha:
            raise ValueError(f"source-model provenance mismatch: {relative}")
    expected = {
        "weights_sha256": registry["winner_best_weights_sha256"],
        "saved_model/saved_model.pb": registry["winner_saved_model_pb_sha256"],
        "dataset_manifest.json": registry["dataset_manifest_sha256"],
    }
    if provenance.get("weights_sha256") != expected["weights_sha256"]:
        raise ValueError("source-model weights identity differs from selected registry")
    for relative in ("saved_model/saved_model.pb", "dataset_manifest.json"):
        if files.get(relative) != expected[relative]:
            raise ValueError(f"source-model {relative} identity differs from selected registry")
    converter = ROOT / "Tools/deploy_candidate_convert.py"
    bindings = {
        "source_provenance_sha256": sha(provenance_path),
        "converter_source_sha256": sha(converter),
        "saved_model_pb_sha256": registry["winner_saved_model_pb_sha256"],
    }
    for key, expected_value in bindings.items():
        if conversion.get(key) != expected_value:
            raise ValueError(f"conversion {key} does not bind the frozen source")


def check_generate_report(text: str) -> None:
    required = ["--target stm32f4", "--name gs_network", "--compression none",
                "--optimization time", "--no-inputs-allocation",
                "--no-outputs-allocation", "--c-api st-ai", "gesture_v7_int8.tflite"]
    missing = [item for item in required if item not in text]
    if missing:
        raise ValueError("official generation report misses fixed options: " + ", ".join(missing))


def instrument_source(source: str) -> str:
    if "gs_cubeai_layer_done(" in source:
        raise ValueError("generated source is already instrumented")
    include = '#include "gs_network.h"'
    if source.count(include) != 1:
        raise ValueError("unexpected generated network include structure")
    result = source.replace(include, include + '\n#include "gs_cubeai_backend.h"')
    observed = re.findall(r"/\* LITE_KERNEL_SECTION END ([^ ]+) \*/", source)
    if observed != GENERATED_MARKERS:
        raise ValueError(f"generated original-layer markers changed: {observed}")
    for index, (name, outputs) in enumerate(zip(LAYER_NAMES, LAYER_OUTPUTS)):
        marker = f"  /* LITE_KERNEL_SECTION END {name} */"
        if result.count(marker) != 1:
            raise ValueError(f"expected one marker for {name}")
        hook = f"\n  if (!gs_cubeai_layer_done({index}U, {outputs}U)) {{ return STAI_ERROR_GENERIC; }}"
        result = result.replace(marker, marker + hook)
    if result.count("gs_cubeai_layer_done(") != 29:
        raise ValueError("instrumentation did not produce exactly 29 layer hooks")
    return result


def backend_for_signature(source: str, signature: str) -> str:
    pattern = r"#define GS_APPROVED_MODEL_SIGNATURE UINT64_C\(0x[0-9a-fA-F]+\)"
    replacement = f"#define GS_APPROVED_MODEL_SIGNATURE UINT64_C({signature})"
    result, count = re.subn(pattern, replacement, source)
    if count != 1:
        raise ValueError("production backend approval signature marker changed")
    return result


def inspect(work: Path, write_review: bool = True) -> dict:
    model = work / "model"
    generated = work / "generated"
    staging = work / "install-staging"
    conversion = json.loads((model / "conversion.json").read_text(encoding="utf-8-sig"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8-sig"))
    provenance_path = work / "source-model/provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8-sig"))
    tflite = model / "gesture_v7_int8.tflite"
    check_conversion(conversion, registry, tflite)
    check_source_provenance(work, conversion, registry, provenance_path, provenance)
    for name in GENERATED_FILES + GENERATED_EVIDENCE:
        if not (generated / name).is_file():
            raise FileNotFoundError(f"missing official generated file: {name}")
    check_generate_report((generated / "gs_network_generate_report.txt").read_text(
        encoding="utf-8", errors="strict"))
    header_text = (generated / "gs_network.h").read_text(encoding="utf-8")
    contract = parse_header_contract(header_text)
    if contract["origin_model_name"] != "gesture_v7_int8":
        raise ValueError("generated origin model name is not gesture_v7_int8")
    if contract["output_scale"] != float(conversion["output_scale"]) or \
            contract["output_zero"] != int(conversion["output_zero"]):
        raise ValueError("generated output quantization differs from frozen conversion")
    generated_hashes = {name: sha(generated / name) for name in GENERATED_FILES}
    evidence_hashes = {name: sha(generated / name) for name in GENERATED_EVIDENCE}
    staged_generated = staging / "Generated"
    staged_generated.mkdir(parents=True, exist_ok=True)
    for name in GENERATED_FILES:
        if name == "gs_network.c":
            patched = instrument_source((generated / name).read_text(encoding="utf-8"))
            (staged_generated / name).write_text(patched, encoding="utf-8")
        else:
            shutil.copy2(generated / name, staged_generated / name)
    baseline_backend = BASELINE / "Modules/StaticRecognition/Src/gs_cubeai_backend.c"
    current_backend = ROOT / "Modules/StaticRecognition/Src/gs_cubeai_backend.c"
    if current_backend.read_bytes() != baseline_backend.read_bytes():
        raise ValueError("production backend differs from frozen release7 before candidate staging")
    staged_backend = staging / "gs_cubeai_backend.c"
    staged_backend.write_text(backend_for_signature(
        current_backend.read_text(encoding="utf-8"), contract["model_signature"]), encoding="utf-8")
    identity = {
        "schema_version": 1,
        "baseline_release": "Build/timing-fix-20260920/release7",
        "baseline_hex_sha256": "a6d65aacff25229bffff66194db18cb7dffa1712c5a608fcb29eea4704f7db47",
        "selected_saved_model_pb_sha256": registry["winner_saved_model_pb_sha256"],
        "selected_registry_sha256": sha(REGISTRY),
        "source_model_provenance_sha256": sha(provenance_path),
        "conversion_json_sha256": sha(model / "conversion.json"),
        "converter_source_sha256": sha(ROOT / "Tools/deploy_candidate_convert.py"),
        "weights_sha256": conversion["weights_sha256"],
        "dataset_manifest_sha256": conversion["dataset_manifest_sha256"],
        "tflite_sha256": conversion["model_sha256"],
        "labels": conversion["labels"],
        "contract": contract,
        "hook_count": 29,
        "generated_markers": GENERATED_MARKERS,
        "hook_names": LAYER_NAMES,
        "hook_outputs": LAYER_OUTPUTS,
        "official_generated_sha256": generated_hashes,
        "official_generation_evidence_sha256": evidence_hashes,
        "staged_generated_sha256": {name: sha(staged_generated / name) for name in GENERATED_FILES},
        "staged_backend_sha256": sha(staged_backend),
        "runtime_library_sha256": sha(ROOT / "Middlewares/ST/AI/Lib/NetworkRuntime1201_CM4_Keil.lib"),
        "stedgeai_executable_sha256": sha(ROOT.parent / "STAI/4.0/Utilities/windows/stedgeai.exe"),
        "scope": "offline Cube.AI candidate identity; no production install, build, hardware, or live gesture claim",
    }
    identity["identity_sha256"] = canonical_sha(identity)
    write_json(work / "candidate-identity.json", identity)
    if write_review:
        write_json(work / "candidate-install-review.json", {
            "mode": "check-only", "check_only": True, "production_modified": False,
            "identity_sha256": identity["identity_sha256"],
            "staging": str(staging.resolve()), "passed": True})
    return identity


def transactional_replace(payloads: dict[Path, bytes], expected_before: dict[Path, str],
                          receipt_path: Path, identity_sha256: str,
                          fail_after: int | None = None) -> dict:
    """Replace a bounded file set and restore every original on any exception.

    Temporary files and backups live beside their destination so every individual
    replace is atomic.  The persistent receipt/backups also permit a later run to
    diagnose an interrupted process; ordinary exceptions are rolled back here.
    """
    ordered = sorted(payloads, key=lambda path: str(path))
    token = identity_sha256[:16]
    temps: dict[Path, Path] = {}
    backups: dict[Path, Path] = {}
    replaced: list[Path] = []
    cleanup_backups = False
    for destination in ordered:
        if not destination.is_file() or sha(destination) != expected_before[destination]:
            raise ValueError(f"production baseline mismatch before transaction: {destination}")
    try:
        for destination in ordered:
            temporary = destination.with_name(f".{destination.name}.candidate-{token}.tmp")
            backup = destination.with_name(f".{destination.name}.rollback-{token}.bak")
            if temporary.exists() or backup.exists():
                raise ValueError(f"stale candidate transaction artifact: {destination}")
            temporary.write_bytes(payloads[destination])
            if sha(temporary) != hashlib.sha256(payloads[destination]).hexdigest():
                raise IOError(f"temporary candidate hash mismatch: {destination}")
            backup.write_bytes(destination.read_bytes())
            if sha(backup) != expected_before[destination]:
                raise IOError(f"rollback backup hash mismatch: {destination}")
            temps[destination] = temporary
            backups[destination] = backup
        write_json(receipt_path, {
            "state": "prepared", "identity_sha256": identity_sha256,
            "production_modified": False,
            "targets": [str(path.resolve()) for path in ordered]})
        for index, destination in enumerate(ordered, 1):
            os.replace(temps[destination], destination)
            replaced.append(destination)
            if fail_after is not None and index == fail_after:
                raise RuntimeError("injected candidate install failure")
        for destination in ordered:
            wanted = hashlib.sha256(payloads[destination]).hexdigest()
            if sha(destination) != wanted:
                raise IOError(f"installed candidate hash mismatch: {destination}")
        result = {
            "state": "installed", "identity_sha256": identity_sha256,
            "production_modified": True,
            "installed_sha256": {str(path.resolve()): sha(path) for path in ordered},
        }
        write_json(receipt_path, result)
        cleanup_backups = True
        return result
    except Exception as exc:
        restored = True
        for destination in reversed(replaced):
            backup = backups.get(destination)
            try:
                if backup is None or not backup.is_file():
                    restored = False
                else:
                    os.replace(backup, destination)
            except OSError:
                restored = False
        for destination, expected in expected_before.items():
            if not destination.is_file() or sha(destination) != expected:
                restored = False
        cleanup_backups = restored
        retained_backups = [str(path.resolve()) for path in backups.values() if path.exists()]
        write_json(receipt_path, {
            "state": "failed", "identity_sha256": identity_sha256,
            "production_modified": not restored, "production_restored": restored,
            "retained_rollback_backups": retained_backups,
            "error": f"{type(exc).__name__}: {exc}"})
        raise
    finally:
        for temporary in temps.values():
            temporary.unlink(missing_ok=True)
        if cleanup_backups:
            for backup in backups.values():
                backup.unlink(missing_ok=True)


def install(work: Path, identity: dict, approval_path: Path) -> None:
    receipt_path = work / "install-attempt.json"
    receipt_path.unlink(missing_ok=True)
    try:
        approval = json.loads(approval_path.read_text(encoding="utf-8-sig"))
        if approval.get("authorized_for_install") is not True or \
                approval.get("identity_sha256") != identity["identity_sha256"]:
            raise ValueError("approval does not authorize this exact candidate identity")
        staging = work / "install-staging"
        destination = ROOT / "Middlewares/ST/AI/Generated"
        baseline_generated = BASELINE / "Middlewares/ST/AI/Generated"
        backend_path = ROOT / "Modules/StaticRecognition/Src/gs_cubeai_backend.c"
        baseline_backend = BASELINE / "Modules/StaticRecognition/Src/gs_cubeai_backend.c"
        manifest_path = ROOT / "Middlewares/ST/AI/manifest.json"
        baseline_manifest = BASELINE / "Middlewares/ST/AI/manifest.json"
        payloads: dict[Path, bytes] = {}
        expected_before: dict[Path, str] = {}
        for name in GENERATED_FILES:
            source = staging / "Generated" / name
            if sha(source) != identity["staged_generated_sha256"][name]:
                raise ValueError(f"staged candidate changed after identity: {name}")
            payloads[destination / name] = source.read_bytes()
            expected_before[destination / name] = sha(baseline_generated / name)
        staged_backend = staging / "gs_cubeai_backend.c"
        if sha(staged_backend) != identity["staged_backend_sha256"]:
            raise ValueError("staged backend changed after identity")
        payloads[backend_path] = staged_backend.read_bytes()
        expected_before[backend_path] = sha(baseline_backend)
        if not baseline_manifest.is_file():
            raise FileNotFoundError("release7 baseline manifest is missing")
        expected_before[manifest_path] = sha(baseline_manifest)
        installed_generated = {
            name: identity["staged_generated_sha256"][name] for name in GENERATED_FILES}
        backend_sha = identity["staged_backend_sha256"]
        manifest = {
        "tool": "ST Edge AI Core 4.0.1-20581 / STM32CubeAI 12.0.1-RC2",
        "model_sha256": identity["tflite_sha256"],
        "approved_weights_sha256": identity["weights_sha256"],
        "dataset_manifest_sha256": identity["dataset_manifest_sha256"],
        "selected_saved_model_pb_sha256": identity["selected_saved_model_pb_sha256"],
        "source_model_provenance_sha256": identity["source_model_provenance_sha256"],
        "conversion_json_sha256": identity["conversion_json_sha256"],
        "converter_source_sha256": identity["converter_source_sha256"],
        "candidate_identity_sha256": identity["identity_sha256"],
        "instrumentation": "29 original-layer end hooks; kernels and weights unchanged",
        "generated_source_sha256": identity["official_generated_sha256"],
        "generation_evidence_sha256": identity["official_generation_evidence_sha256"],
        "installed_generated_sha256": installed_generated,
        "backend_sha256": backend_sha,
        "runtime_library_sha256": identity["runtime_library_sha256"],
        }
        manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        payloads[manifest_path] = manifest_bytes
        result = transactional_replace(payloads, expected_before, receipt_path,
                                       identity["identity_sha256"])
        write_json(work / "install-result.json", {
            "installed": True, "identity_sha256": identity["identity_sha256"],
            "files": installed_generated, "backend_sha256": backend_sha,
            "transaction": result})
        write_json(work / "candidate-install-review.json", {
            "mode": "install", "check_only": False, "production_modified": True,
            "identity_sha256": identity["identity_sha256"], "passed": True,
            "install_attempt": str(receipt_path.resolve())})
    except Exception as exc:
        if not receipt_path.exists():
            write_json(receipt_path, {
                "state": "failed-before-modification",
                "identity_sha256": identity.get("identity_sha256"),
                "production_modified": False, "production_restored": True,
                "error": f"{type(exc).__name__}: {exc}"})
        write_json(work / "candidate-install-review.json", {
            "mode": "install", "check_only": False,
            "production_modified": json.loads(receipt_path.read_text(encoding="utf-8"))
                .get("production_modified", False),
            "identity_sha256": identity.get("identity_sha256"), "passed": False,
            "install_attempt": str(receipt_path.resolve()),
            "error": f"{type(exc).__name__}: {exc}"})
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, default=DEFAULT_WORK)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--approval", type=Path)
    args = parser.parse_args()
    identity = inspect(args.work.resolve(), write_review=not args.install)
    if args.install:
        if args.approval is None:
            raise SystemExit("--install requires --approval binding candidate identity_sha256")
        install(args.work.resolve(), identity, args.approval.resolve())
    print(json.dumps({"mode": "install" if args.install else "check-only",
                      "identity_sha256": identity["identity_sha256"],
                      "model_signature": identity["contract"]["model_signature"],
                      "activation_bytes": identity["contract"]["activation_bytes"]}, indent=2))


if __name__ == "__main__":
    main()
