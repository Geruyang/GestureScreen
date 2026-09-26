"""Validate the staged v7 production backend against uninstrumented Cube.AI."""
from pathlib import Path
import argparse
import ctypes as C
import hashlib
import json
import subprocess
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORK = ROOT / "Build/deployment-new-model-20260920"


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_sha(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, default=DEFAULT_WORK)
    args = parser.parse_args()
    work = args.work.resolve(); host = work / "host"; host.mkdir(parents=True, exist_ok=True)
    identity = json.loads((work / "candidate-identity.json").read_text(encoding="utf-8-sig"))
    conversion = json.loads((work / "model/conversion.json").read_text(encoding="utf-8-sig"))
    claimed_identity = identity.get("identity_sha256")
    identity_payload = dict(identity); identity_payload.pop("identity_sha256", None)
    if claimed_identity != canonical_sha(identity_payload):
        raise ValueError("candidate identity file is not self-authenticating")
    if sha(work / "model/conversion.json") != identity["conversion_json_sha256"]:
        raise ValueError("conversion JSON changed after candidate identity")
    generated = work / "install-staging/Generated"
    backend = work / "install-staging/gs_cubeai_backend.c"
    gcc = ROOT.parent / "STAI/4.0/Utilities/windows/mingw64/bin/gcc.exe"
    libdir = ROOT / "Build/cubeai-migration/validate-work/inspector_gs_network/workspace/lib/static"
    sources = [generated / "gs_network.c", generated / "gs_network_data.c", backend]
    for name, expected_sha in identity["staged_generated_sha256"].items():
        if sha(generated / name) != expected_sha:
            raise ValueError(f"staged generated file changed after identity: {name}")
    if sha(backend) != identity["staged_backend_sha256"]:
        raise ValueError("staged backend changed after identity")
    source_hashes = {str(path): sha(path) for path in sources}
    # Use an identity-specific filename because Windows keeps a loaded DLL
    # locked until its host process exits; never overwrite an older run.
    dll = host / f"candidate-production-{claimed_identity[:16]}.dll"
    command = [str(gcc), "-shared", "-O2", "-std=c99", "-DGS_STATIC_USE_CUBEAI=1",
        "-I" + str(ROOT / "Middlewares/ST/AI/Inc"), "-I" + str(generated),
        "-I" + str(ROOT / "Modules/StaticRecognition/Inc"),
        "-I" + str(ROOT / "Modules/Vision/Inc"), *map(str, sources), "-L" + str(libdir),
        "-lruntime", "-lst_cmsis_nn", "-lcmsis-nn", "-lm", "-o", str(dll)]
    subprocess.run(command, check=True)
    lib = C.CDLL(str(dll)); callback_type = C.CFUNCTYPE(C.c_bool, C.c_void_p, C.c_size_t, C.c_uint32)
    execute = lib.gs_cubeai_execute; execute.restype = C.c_int
    execute.argtypes = [C.c_void_p,C.c_size_t,C.c_void_p,C.c_size_t,C.POINTER(C.c_float),
                        C.POINTER(C.c_int32),callback_type,C.c_void_p]
    if lib.gs_cubeai_contract_status() != 0: raise RuntimeError("staged backend contract rejected")
    inputs = np.load(work / "model/quantized_inputs.npy")
    expected = np.load(host / "cubeai_logits.npy")
    classes = len(conversion["labels"]); hooks = identity["hook_outputs"]
    if inputs.shape[0] != expected.shape[0] or expected.shape[1] != classes:
        raise ValueError("host reference shape mismatch")
    guarded = np.full(classes + 8, 85, dtype=np.int8)
    scale = C.c_float(); zero = C.c_int32(); seen = []
    @callback_type
    def progress(context, layer, outputs):
        seen.append((layer, outputs)); return True
    def call(index, callback=progress):
        return execute(inputs[index].ctypes.data, 9216, guarded.ctypes.data + 4, classes,
                       C.byref(scale), C.byref(zero), callback, None)
    for index in range(len(inputs)):
        seen.clear(); guarded.fill(85)
        if call(index) != 0: raise AssertionError(("execute", index))
        if not np.array_equal(guarded[4:4+classes], expected[index]): raise AssertionError(("logits", index))
        if not (np.all(guarded[:4] == 85) and np.all(guarded[4+classes:] == 85)):
            raise AssertionError(("guard", index))
        if seen != list(enumerate(hooks)): raise AssertionError(("hooks", index, seen))
        if scale.value != np.float32(conversion["output_scale"]) or zero.value != int(conversion["output_zero"]):
            raise AssertionError(("quantization", scale.value, zero.value))
    for stop in range(len(hooks)):
        seen.clear(); guarded.fill(85); scale.value = -1; zero.value = 999
        @callback_type
        def cancel(context, layer, outputs, stop=stop):
            seen.append((layer, outputs)); return layer != stop
        if call(0, cancel) != 4 or seen != list(enumerate(hooks[:stop+1])):
            raise AssertionError(("cancel", stop, seen))
        if not np.all(guarded == 85) or scale.value != -1 or zero.value != 999:
            raise AssertionError(("partial publication", stop))
        if call(0) != 0 or not np.array_equal(guarded[4:4+classes], expected[0]):
            raise AssertionError(("recovery", stop))
    invalid = [(None,9216,classes),(inputs[0].ctypes.data,9215,classes),
               (inputs[0].ctypes.data+1,9216,classes),(inputs[0].ctypes.data,9216,classes-1)]
    for pointer, count, output_count in invalid:
        if execute(pointer,count,guarded.ctypes.data+4,output_count,C.byref(scale),C.byref(zero),progress,None) != 2:
            raise AssertionError(("invalid argument", pointer, count, output_count))
    for path, digest in source_hashes.items():
        if sha(path) != digest: raise AssertionError("source changed during backend check: " + path)
    report = {"vectors": len(inputs), "identity_sha256": identity["identity_sha256"],
        "byte_exact_to_uninstrumented_cubeai": True, "output_guards_passed": True,
        "output_scale": conversion["output_scale"], "output_zero": conversion["output_zero"],
        "cancel_recover_points": len(hooks), "invalid_inputs": len(invalid),
        "source_sha256": source_hashes, "dll_sha256": sha(dll),
        "scope": "staged production C on vendor host runtime; no production install, board, timing, or live gesture claim"}
    (host / "candidate-production-check.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__": main()
