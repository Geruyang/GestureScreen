"""Validate official generated runtime on frozen train/validation vectors."""
from pathlib import Path
import ctypes as C
import subprocess
import json
import re
import hashlib
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'Build/deployment-v12-20260922'
GEN=WORK/'generated'; HOST=WORK/'host'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    HOST.mkdir(exist_ok=True)
    gcc=ROOT.parent/'STAI/4.0/Utilities/windows/mingw64/bin/gcc.exe'
    libdir=ROOT/'Build/cubeai-migration/validate-work/inspector_gs_network/workspace/lib/static'
    dll=HOST/'gs_network.dll'
    subprocess.run([str(gcc),'-shared','-O2','-std=c99','-I'+str(ROOT/'Middlewares/ST/AI/Inc'),
        '-I'+str(GEN),str(GEN/'gs_network.c'),str(GEN/'gs_network_data.c'),'-L'+str(libdir),
        '-lruntime','-lst_cmsis_nn','-lcmsis-nn','-lm','-o',str(dll)],check=True)
    header=(GEN/'gs_network.h').read_text()
    arena_size=int(re.search(r'ACTIVATIONS_SIZE_BYTES\s+\((\d+)\)',header)[1])
    output_size=int(re.search(r'STAI_GS_NETWORK_OUT_SIZE_BYTES\s+\((\d+)\)',header)[1])
    lib=C.CDLL(str(dll));lib.stai_gs_network_get_context_size.restype=C.c_uint32
    ctx=C.create_string_buffer(lib.stai_gs_network_get_context_size());arena=C.create_string_buffer(arena_size)
    lib.stai_gs_network_init.argtypes=[C.c_void_p];assert lib.stai_gs_network_init(ctx)==0
    def setter(name,address):
        fn=getattr(lib,'stai_gs_network_set_'+name);fn.argtypes=[C.c_void_p,C.POINTER(C.c_void_p),C.c_uint32]
        assert fn(ctx,(C.c_void_p*1)(address),1)==0
    setter('activations',C.addressof(arena));run=lib.stai_gs_network_run;run.argtypes=[C.c_void_p,C.c_int]
    data=np.load(WORK/'model/quantized-inputs.npy');tflite=np.load(WORK/'model/tflite-logits.npy')
    floating=np.load(WORK/'model/torch-logits.npy');labels=np.load(WORK/'model/labels.npy')
    export=json.loads((WORK/'model/export.json').read_text())
    out=np.zeros(output_size,dtype=np.int8);actual=np.empty_like(tflite)
    for i,x in enumerate(data):
        setter('inputs',x.ctypes.data);setter('outputs',out.ctypes.data);assert run(ctx,1)==0;actual[i]=out[:6]
    np.save(HOST/'cubeai-logits.npy',actual)
    metrics={}
    for split in ('train','validation'):
        m=np.array([r['split']==split for r in export['samples']]);a=actual[m].argmax(1)
        metrics[split]=dict(count=int(m.sum()),float_correct=int((floating[m].argmax(1)==labels[m]).sum()),
            tflite_correct=int((tflite[m].argmax(1)==labels[m]).sum()),cubeai_correct=int((a==labels[m]).sum()),
            cubeai_tflite_top1_agreement=int((a==tflite[m].argmax(1)).sum()),
            cubeai_float_top1_agreement=int((a==floating[m].argmax(1)).sum()))
    result=dict(dll_sha256=sha(dll),activation_bytes=arena_size,samples=len(data),metrics=metrics,
        max_tflite_logit_delta=int(np.abs(actual.astype(np.int16)-tflite.astype(np.int16)).max()),
        generated_sha256={p.name:sha(p) for p in GEN.glob('gs_network*') if p.is_file()},test_opened=False,
        scope='Official host runtime on frozen train/validation vectors; not on-target accuracy or latency.')
    (HOST/'comparison.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2),flush=True)
if __name__=='__main__':main()
