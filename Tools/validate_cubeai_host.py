"""Run the actual generated ST.AI DLL on the fixed int8 regression corpus."""
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'Build/cubeai-migration'

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    dllpath = WORK / 'host-validation/gs_network.dll'
    with os.add_dll_directory(str(ROOT.parent / 'STAI/4.0/Utilities/windows/mingw64/bin')):
        lib = C.CDLL(str(dllpath))
    sizefn = lib.stai_gs_network_get_context_size
    sizefn.restype = C.c_uint32
    ctx = C.create_string_buffer(sizefn())
    arena = C.create_string_buffer(58624)
    init = lib.stai_gs_network_init
    init.argtypes = [C.c_void_p]
    assert init(ctx) == 0
    def setter(name, addr):
        fn = getattr(lib, 'stai_gs_network_set_' + name)
        fn.argtypes = [C.c_void_p, C.POINTER(C.c_void_p), C.c_uint32]
        pointers = (C.c_void_p * 1)(addr)
        assert fn(ctx, pointers, 1) == 0, name
    setter('activations', C.addressof(arena))
    run = lib.stai_gs_network_run
    run.argtypes = [C.c_void_p, C.c_int]
    inputs = np.load(WORK / 'validation-inputs/inputs.npy')
    expected = np.load(WORK / 'validation-inputs/reference_logits.npy')
    actual = np.zeros_like(expected)
    for i, x in enumerate(inputs):
        out = np.zeros(8, dtype=np.int8)
        setter('inputs', x.ctypes.data)
        setter('outputs', out.ctypes.data)
        assert run(ctx, 1) == 0, i
        actual[i] = out[:5]
    delta = actual.astype(np.int16) - expected.astype(np.int16)
    report = {'dll_sha256': sha(dllpath), 'samples': len(inputs), 'equal_elements': int((delta == 0).sum()),
              'elements': int(delta.size), 'max_absolute_delta': int(np.abs(delta).max()),
              'top1_matches': int((actual.argmax(1) == expected.argmax(1)).sum()),
              'bit_exact': bool(np.array_equal(actual, expected)),
              'mismatches': [{'sample': i, 'reference': expected[i].tolist(), 'cubeai': actual[i].tolist()}
                             for i in range(len(inputs)) if np.any(delta[i])],
              'scope': 'Generated ST.AI C with vendor host runtime; not MCU timing or gesture accuracy'}
    np.save(WORK / 'host-validation/cubeai_logits.npy', actual)
    (WORK / 'host-validation/numerical-review.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if report['bit_exact'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
