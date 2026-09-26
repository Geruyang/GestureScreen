"""Production backend parity, cancellation/recovery, and buffer guards."""
from pathlib import Path
import ctypes as C
import hashlib
import json
import subprocess
import numpy as np
ROOT=Path(__file__).resolve().parents[1];WORK=ROOT/'Build/deployment-v12-20260922'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    gen=ROOT/'Middlewares/ST/AI/Generated';backend=ROOT/'Modules/StaticRecognition/Src/gs_cubeai_backend.c'
    stamp=json.loads((WORK/'install.json').read_text())
    for name,digest in stamp['generated_sha256'].items():assert sha(gen/name)==digest,name
    assert sha(backend)==stamp['backend_sha256']
    gcc=ROOT.parent/'STAI/4.0/Utilities/windows/mingw64/bin/gcc.exe'
    libs=ROOT/'Build/cubeai-migration/validate-work/inspector_gs_network/workspace/lib/static'
    dll=WORK/'host/production.dll'
    sources=[gen/'gs_network.c',gen/'gs_network_data.c',backend]
    includes=[ROOT/'Middlewares/ST/AI/Inc',gen,ROOT/'Modules/StaticRecognition/Inc',ROOT/'Modules/Vision/Inc']
    subprocess.run([str(gcc),'-shared','-O2','-std=c99','-DGS_STATIC_USE_CUBEAI=1',
        *['-I'+str(p) for p in includes],*map(str,sources),'-L'+str(libs),'-lruntime','-lst_cmsis_nn','-lcmsis-nn','-lm','-o',str(dll)],check=True)
    lib=C.CDLL(str(dll));cbtype=C.CFUNCTYPE(C.c_bool,C.c_void_p,C.c_size_t,C.c_uint32)
    run=lib.gs_cubeai_execute;run.restype=C.c_int
    run.argtypes=[C.c_void_p,C.c_size_t,C.c_void_p,C.c_size_t,C.POINTER(C.c_float),C.POINTER(C.c_int32),cbtype,C.c_void_p]
    assert lib.gs_cubeai_contract_status()==0
    inputs=np.load(WORK/'model/quantized-inputs.npy');expected=np.load(WORK/'host/cubeai-logits.npy')
    output=np.full(14,85,dtype=np.int8);scale=C.c_float();zero=C.c_int32();seen=[]
    @cbtype
    def progress(ctx,layer,size):seen.append((layer,size));return True
    hooks=list(enumerate(stamp['hook_outputs']))
    def call(i,cb=progress):return run(inputs[i].ctypes.data,27648,output.ctypes.data+4,6,C.byref(scale),C.byref(zero),cb,None)
    for i in range(len(inputs)):
        seen.clear();output.fill(85);assert call(i)==0,i
        assert np.array_equal(output[4:10],expected[i]),i
        assert np.all(output[:4]==85) and np.all(output[10:]==85)
        assert seen==hooks,(i,seen)
    for stop in range(29):
        seen.clear();output.fill(85);scale.value=-1;zero.value=999
        @cbtype
        def cancel(ctx,layer,size):seen.append((layer,size));return layer!=stop
        assert call(0,cancel)==4 and seen==hooks[:stop+1]
        assert np.all(output==85) and scale.value==-1 and zero.value==999
        assert call(0)==0 and np.array_equal(output[4:10],expected[0])
    for pointer,count,classes in ((None,27648,6),(inputs[0].ctypes.data,27647,6),(inputs[0].ctypes.data+1,27648,6),(inputs[0].ctypes.data,27648,5)):
        assert run(pointer,count,output.ctypes.data+4,classes,C.byref(scale),C.byref(zero),progress,None)==2
    record=dict(vectors=len(inputs),byte_exact_to_official_host=True,guard_bytes_passed=True,
        cancel_recovery_points=29,invalid_inputs=4,dll_sha256=sha(dll),source_sha256={str(p):sha(p) for p in sources})
    (WORK/'host/production-check.json').write_text(json.dumps(record,indent=2),encoding='utf-8');print(json.dumps(record,indent=2))
if __name__=='__main__':main()
