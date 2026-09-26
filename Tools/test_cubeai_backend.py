"""Compile the production wrapper/generated source against ST's host runtime.

Verify all fixed vectors plus cancellation at every layer and recovery; no MCU access.
Requires the host libraries prepared by stedgeai validate (its Windows make may fail).
"""
import ctypes as C
import json
from pathlib import Path
import subprocess
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'Build/cubeai-migration'
SDK = ROOT.parent / 'STAI/4.0'
DLL = WORK / 'host-validation/gs_backend.dll'
GCC = SDK / 'Utilities/windows/mingw64/bin/gcc.exe'
include = [ROOT/'Middlewares/ST/AI/Inc', ROOT/'Middlewares/ST/AI/Generated',
           ROOT/'Modules/StaticRecognition/Inc', ROOT/'Modules/Vision/Inc']
sources = [ROOT/'Middlewares/ST/AI/Generated/gs_network.c',
           ROOT/'Middlewares/ST/AI/Generated/gs_network_data.c',
           ROOT/'Modules/StaticRecognition/Src/gs_cubeai_backend.c']
subprocess.run([str(GCC), '-shared', '-O2', '-std=c99', '-DGS_STATIC_USE_CUBEAI=1',
                *['-I'+str(p) for p in include], *map(str,sources),
                '-L'+str(WORK/'validate-work/inspector_gs_network/workspace/lib/static'),
                '-lruntime', '-lst_cmsis_nn', '-lcmsis-nn', '-lm', '-o', str(DLL)], check=True)
lib = C.CDLL(str(DLL))
CB = C.CFUNCTYPE(C.c_bool, C.c_void_p, C.c_size_t, C.c_uint32)
fn = lib.gs_cubeai_execute
fn.argtypes = [C.c_void_p, C.c_size_t, C.c_void_p, CB, C.c_void_p]
fn.restype = C.c_int
inputs = np.load(WORK/'validation-inputs/inputs.npy')
expected = np.load(WORK/'host-validation/cubeai_logits.npy')
out = np.zeros(5, dtype=np.int8)
seen = []
@CB
def progress(ctx, layer, count):
    seen.append((layer, count))
    return True
for i,x in enumerate(inputs):
    seen.clear()
    assert fn(x.ctypes.data, x.size, out.ctypes.data, progress, None) == 0
    assert np.array_equal(out, expected[i]), i
    assert [p[0] for p in seen] == list(range(29)), seen
    assert all(p[1] > 0 for p in seen)
for stop in range(29):
    seen.clear()
    @CB
    def cancel(ctx, layer, count):
        seen.append(layer)
        return layer != stop
    out.fill(85)
    assert fn(inputs[0].ctypes.data, 9216, out.ctypes.data, cancel, None) == 4
    assert seen == list(range(stop+1)), (stop, seen)
    assert np.all(out == 85), 'partial result published'
    assert fn(inputs[0].ctypes.data, 9216, out.ctypes.data, progress, None) == 0
    assert np.array_equal(out, expected[0]), 'recovery failed'
assert fn(None, 9216, out.ctypes.data, progress, None) == 2
assert fn(inputs[0].ctypes.data, 9215, out.ctypes.data, progress, None) == 2
assert fn(inputs[0].ctypes.data+1, 9216, out.ctypes.data, progress, None) == 2
report = {'vectors':63, 'wrapper_matches_unmodified_cubeai':True,
          'cancel_and_recover_layers':29, 'invalid_input_checks':3,
          'scope':'host vendor runtime, not Cortex-M4 numerical/timing validation'}
(WORK/'host-validation/backend-tests.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report))
