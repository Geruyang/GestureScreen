"""Compare official generated host runtime against frozen float/TFLite outputs."""
from pathlib import Path
import ctypes as C
import subprocess,json,re,hashlib
import numpy as np
ROOT=Path(__file__).resolve().parents[1];WORK=ROOT/'Build/deployment-v5'
GEN=WORK/'generated';HOST=WORK/'host';HOST.mkdir(exist_ok=True)
gcc=ROOT.parent/'STAI/4.0/Utilities/windows/mingw64/bin/gcc.exe'
libdir=ROOT/'Build/cubeai-migration/validate-work/inspector_gs_network/workspace/lib/static'
dll=HOST/'gs_network.dll'
subprocess.run([str(gcc),'-shared','-O2','-std=c99','-I'+str(ROOT/'Middlewares/ST/AI/Inc'),
 '-I'+str(GEN),str(GEN/'gs_network.c'),str(GEN/'gs_network_data.c'),'-L'+str(libdir),
 '-lruntime','-lst_cmsis_nn','-lcmsis-nn','-lm','-o',str(dll)],check=True)
lib=C.CDLL(str(dll));size=lib.stai_gs_network_get_context_size;size.restype=C.c_uint32
ctx=C.create_string_buffer(size());arena=C.create_string_buffer(int(re.search(r'ACTIVATIONS_SIZE_BYTES\s+\((\d+)\)',(GEN/'gs_network.h').read_text())[1]))
init=lib.stai_gs_network_init;init.argtypes=[C.c_void_p];assert init(ctx)==0
def setter(name,addr):
 f=getattr(lib,'stai_gs_network_set_'+name);f.argtypes=[C.c_void_p,C.POINTER(C.c_void_p),C.c_uint32]
 assert f(ctx,(C.c_void_p*1)(addr),1)==0
setter('activations',C.addressof(arena));run=lib.stai_gs_network_run;run.argtypes=[C.c_void_p,C.c_int]
x=np.load(WORK/'model/quantized_inputs.npy');t=np.load(WORK/'model/tflite_logits.npy')
flo=np.load(WORK/'model/float_logits.npy');y=np.load(WORK/'model/labels.npy')
samples=json.loads((WORK/'model/dataset-review.json').read_text())['samples']
out_bytes=int(re.search(r'STAI_GS_NETWORK_OUT_SIZE_BYTES\s+\((\d+)\)',(GEN/'gs_network.h').read_text())[1])
out=np.zeros(out_bytes,dtype=np.int8);actual=np.empty_like(t)
for i,a in enumerate(x):
 setter('inputs',a.ctypes.data);setter('outputs',out.ctypes.data);assert run(ctx,1)==0
 actual[i]=out[:7]
np.save(HOST/'cubeai_logits.npy',actual)
metrics={}
for split in ['train','validation','test']:
 m=np.array([r['split']==split for r in samples]);q=actual[m].argmax(1)
 metrics[split]={'count':int(m.sum()),'float_correct':int((flo[m].argmax(1)==y[m]).sum()),
  'tflite_correct':int((t[m].argmax(1)==y[m]).sum()),'cubeai_correct':int((q==y[m]).sum()),
  'cubeai_tflite_top1_agreement':int((q==t[m].argmax(1)).sum())}
r={'dll_sha256':hashlib.sha256(dll.read_bytes()).hexdigest(),'samples':len(x),
 'max_logit_delta':int(abs(actual.astype(np.int16)-t.astype(np.int16)).max()),'metrics':metrics,
 'scope':'official host runtime; no Cortex-M4 per-vector accuracy claim; frozen candidate, not tuning'}
(HOST/'comparison.json').write_text(json.dumps(r,indent=2));print(json.dumps(r,indent=2))
