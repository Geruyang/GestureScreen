"""Check the actual seven-class production wrapper, guards and cancellation."""
from pathlib import Path
import ctypes as C,json,subprocess,hashlib
import numpy as np
ROOT=Path(__file__).resolve().parents[1];WORK=ROOT/'Build/deployment-v5';HOST=WORK/'host'
gcc=ROOT.parent/'STAI/4.0/Utilities/windows/mingw64/bin/gcc.exe'
inc=[ROOT/'Middlewares/ST/AI/Inc',ROOT/'Middlewares/ST/AI/Generated',ROOT/'Modules/StaticRecognition/Inc',ROOT/'Modules/Vision/Inc']
src=[ROOT/'Middlewares/ST/AI/Generated/gs_network.c',ROOT/'Middlewares/ST/AI/Generated/gs_network_data.c',ROOT/'Modules/StaticRecognition/Src/gs_cubeai_backend.c']
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
hashes={str(p):sha(p) for p in src}
dll=HOST/'production.dll'
subprocess.run([str(gcc),'-shared','-O2','-std=c99','-DGS_STATIC_USE_CUBEAI=1',*['-I'+str(p) for p in inc],*map(str,src),
 '-L'+str(ROOT/'Build/cubeai-migration/validate-work/inspector_gs_network/workspace/lib/static'),
 '-lruntime','-lst_cmsis_nn','-lcmsis-nn','-lm','-o',str(dll)],check=True)
lib=C.CDLL(str(dll));CB=C.CFUNCTYPE(C.c_bool,C.c_void_p,C.c_size_t,C.c_uint32)
fn=lib.gs_cubeai_execute;fn.restype=C.c_int
fn.argtypes=[C.c_void_p,C.c_size_t,C.c_void_p,C.c_size_t,C.POINTER(C.c_float),C.POINTER(C.c_int32),CB,C.c_void_p]
assert lib.gs_cubeai_contract_status()==0
x=np.load(WORK/'model/quantized_inputs.npy');expected=np.load(HOST/'cubeai_logits.npy')
out=np.full(16,85,dtype=np.int8);scale=C.c_float();zero=C.c_int32();seen=[]
@CB
def progress(ctx,layer,count):seen.append((layer,count));return True
def call(i,cb=progress):return fn(x[i].ctypes.data,9216,out.ctypes.data+4,7,C.byref(scale),C.byref(zero),cb,None)
for i in range(len(x)):
 seen.clear();out.fill(85);assert call(i)==0
 assert np.array_equal(out[4:11],expected[i]),i
 assert np.all(out[:4]==85) and np.all(out[11:]==85)
 assert [p[0] for p in seen]==list(range(29)) and seen[-1]==(28,7)
 assert scale.value==np.float32(.08847017586231232) and zero.value==-6
for stop in range(29):
 seen.clear();out.fill(85);scale.value=-1;zero.value=999
 @CB
 def cancel(ctx,layer,count):seen.append(layer);return layer!=stop
 assert call(0,cancel)==4 and seen==list(range(stop+1))
 assert np.all(out==85) and scale.value==-1 and zero.value==999
 assert call(0)==0 and np.array_equal(out[4:11],expected[0])
for ptr,n,m in [(None,9216,7),(x[0].ctypes.data,9215,7),(x[0].ctypes.data+1,9216,7),(x[0].ctypes.data,9216,6)]:
 assert fn(ptr,n,out.ctypes.data+4,m,C.byref(scale),C.byref(zero),progress,None)==2
for path,digest in hashes.items():assert sha(Path(path))==digest,'source changed during test'
r={'vectors':len(x),'byte_exact_to_uninstrumented_cubeai':True,'output_guards_passed':True,
 'cancel_recover_points':29,'invalid_inputs':4,'source_sha256':hashes,'dll_sha256':sha(dll),'scope':'production C on vendor host runtime'}
(HOST/'production-check.json').write_text(json.dumps(r,indent=2));print(json.dumps(r,indent=2))
