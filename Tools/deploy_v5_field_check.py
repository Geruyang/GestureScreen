"""Offline Cube.AI classification of captured diagnostic frames; never trains."""
from pathlib import Path
import argparse,ctypes as C,json,re,hashlib
import numpy as np
ROOT=Path(__file__).resolve().parents[1];WORK=ROOT/'Build/deployment-v5'
a=argparse.ArgumentParser();a.add_argument('capture',type=Path);args=a.parse_args()
capture=args.capture.resolve();host=WORK/'host'
pre=C.CDLL(str(host/'preprocess.dll'));pre.check_frame.argtypes=[C.c_void_p,C.c_uint,C.c_uint,C.c_int,C.c_void_p]
lib=C.CDLL(str(host/'gs_network.dll'));lib.stai_gs_network_get_context_size.restype=C.c_uint32
header=(WORK/'generated/gs_network.h').read_text()
context=C.create_string_buffer(lib.stai_gs_network_get_context_size())
arena=C.create_string_buffer(int(re.search(r'ACTIVATIONS_SIZE_BYTES\s+\((\d+)\)',header)[1]))
lib.stai_gs_network_init.argtypes=[C.c_void_p]
lib.stai_gs_network_run.argtypes=[C.c_void_p,C.c_int]
def setter(name,address):
 fn=getattr(lib,'stai_gs_network_set_'+name);fn.argtypes=[C.c_void_p,C.POINTER(C.c_void_p),C.c_uint]
 assert fn(context,(C.c_void_p*1)(address),1)==0
labels=['POINT_LEFT','POINT_RIGHT','FIST','PALM','V_SIGN','OTHER','EMPTY']
results=[]
for path in sorted(capture.glob('frame-*.rgb565')):
 raw=path.read_bytes();assert len(raw)==153600
 buf=C.create_string_buffer(raw);tensor=np.zeros(9216,dtype=np.int8)
 quality=pre.check_frame(buf,len(raw),640,0,tensor.ctypes.data)
 logits=np.zeros(int(re.search(r'STAI_GS_NETWORK_OUT_SIZE_BYTES\s+\((\d+)\)',header)[1]),dtype=np.int8)
 assert lib.stai_gs_network_init(context)==0
 setter('activations',C.addressof(arena));setter('inputs',tensor.ctypes.data);setter('outputs',logits.ctypes.data)
 assert lib.stai_gs_network_run(context,1)==0
 z=logits[:7].astype(np.float64)*0.08847017586231232;prob=np.exp(z-z.max());prob/=prob.sum()
 results.append({'file':str(path),'raw_sha256':hashlib.sha256(raw).hexdigest(),'preprocess_status':quality,'logits':logits[:7].tolist(),'scores':prob.tolist(),'top1':labels[int(prob.argmax())]})
out=capture/'offline-host-diagnostic.json'
out.write_text(json.dumps({'scope':'diagnostic captured images, no fitting or threshold changes; not a Cortex-M4 output comparison','class_order':labels,'host_library_sha256':hashlib.sha256((host/'gs_network.dll').read_bytes()).hexdigest(),'frames':results},indent=2))
print(json.dumps(results,indent=2))
