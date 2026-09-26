"""用真实公开五类权重逐字节比较标量 C 后端和 TFLite 整数参考内核。"""
from __future__ import annotations

import argparse
import ctypes as ct
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model_package import tensorflow


def compare(model, library, output):
    tf = tensorflow()
    import numpy as np
    interpreter = tf.lite.Interpreter(model_path=str(model), experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_REF)
    interpreter.allocate_tensors()
    input_info, output_info = interpreter.get_input_details()[0], interpreter.get_output_details()[0]
    count = int(np.prod(output_info["shape"]))
    dll = ct.CDLL(str(library.resolve()))
    run = dll.gs_model_raw_run
    run.argtypes = [ct.POINTER(ct.c_int8), ct.POINTER(ct.c_int8)]
    run.restype = ct.c_int
    rng = np.random.default_rng(20260915)
    vectors = [np.full((1, 96, 96, 1), value, dtype=np.int8) for value in (-128, -1, 0, 1, 127)]
    vectors += [np.arange(9216, dtype=np.int32).astype(np.int8).reshape(1, 96, 96, 1)]
    vectors += [rng.integers(-128, 128, size=(1, 96, 96, 1), dtype=np.int8) for _ in range(44)]
    maximum_error = 0
    for i, vector in enumerate(vectors):
        interpreter.set_tensor(input_info["index"], vector)
        interpreter.invoke()
        expected = interpreter.get_tensor(output_info["index"]).reshape(-1)
        actual = np.zeros(count, dtype=np.int8)
        status = run(vector.ctypes.data_as(ct.POINTER(ct.c_int8)), actual.ctypes.data_as(ct.POINTER(ct.c_int8)))
        if status != 0:
            raise AssertionError(f"case {i}: C status {status}")
        error = int(np.abs(expected.astype(np.int16) - actual.astype(np.int16)).max())
        maximum_error = max(maximum_error, error)
        if error:
            raise AssertionError(f"case {i}: int8 mismatch expected={expected.tolist()} actual={actual.tolist()}")
    get_model = dll.gs_model_network
    get_model.restype = ct.c_void_p
    execute = dll.gs_int8_execute
    execute.argtypes = [ct.c_void_p, ct.c_void_p, ct.c_size_t, ct.c_void_p, ct.c_size_t, ct.c_void_p, ct.c_size_t]
    execute.restype = ct.c_int
    minimal_workspace = (ct.c_int8 * 1)()
    result = (ct.c_int8 * count)()
    if execute(get_model(), vectors[0].ctypes.data, 9216, result, count, minimal_workspace, 1) != 2:
        raise AssertionError("undersized workspace did not fail with GS_AI_INVALID_ARGUMENT")
    candidate_gate_rejected = None
    if count == 7:
        class Ai(ct.Structure):
            _fields_ = [("backend", ct.c_void_p), ("ready", ct.c_uint8)]
        candidate = dll.gs_model_candidate_backend
        candidate.restype = ct.c_void_p
        initialize = dll.gs_ai_init
        initialize.argtypes = [ct.POINTER(Ai), ct.c_void_p]
        initialize.restype = ct.c_int
        ai = Ai()
        candidate_gate_rejected = initialize(ct.byref(ai), candidate()) == 3 and ai.ready == 0
        if not candidate_gate_rejected:
            raise AssertionError("unaccepted seven-class candidate bypassed business gate")
    weights_scope = "real public five-class weights" if count == 5 else "synthetic software-test seven-class head plus public backbone; temporary weights destroyed by caller"
    report = dict(scope=f"50 synthetic numerical vectors using {weights_scope}; not gesture accuracy or STM32 timing",
                  vectors=len(vectors), output_count=count, maximum_int8_error=maximum_error,
                  tensorflow=tf.__version__, reference_kernel="BUILTIN_REF", compiled_c="MSVC C11 /O2 /W4 /WX",
                  workspace_underflow_rejected=True, unaccepted_candidate_gate_rejected=candidate_gate_rejected,
                  validated_for_business=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path)
    parser.add_argument("library", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    compare(args.model, args.library, args.report)
