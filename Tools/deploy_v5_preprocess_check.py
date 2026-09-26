"""Compare production C preprocessing with all archived training-reader tensors."""
from pathlib import Path
import ctypes as C,json,subprocess,hashlib
import numpy as np
ROOT=Path(__file__).resolve().parents[1];WORK=ROOT/'Build/deployment-v5'
HOST=WORK/'host';PACKAGE=ROOT.parent/'Gesture_Model_Package'
bridge=HOST/'preprocess_bridge.c'
bridge.write_text('#include "gs_preprocess.h"\nint check_frame(const unsigned char *raw, unsigned bytes, unsigned stride, int order, signed char *out) { gs_rgb565_frame_t f={raw,bytes,320,240,stride,(gs_rgb565_byte_order_t)order}; return gs_preprocess_rgb565(&f,out,9216,0,0); }\n')
gcc=ROOT.parent/'STAI/4.0/Utilities/windows/mingw64/bin/gcc.exe';dll=HOST/'preprocess.dll'
subprocess.run([str(gcc),'-shared','-O2','-I'+str(ROOT/'Modules/Vision/Inc'),str(bridge),
 str(ROOT/'Modules/Vision/Src/gs_preprocess.c'),'-o',str(dll)],check=True)
lib=C.CDLL(str(dll));fn=lib.check_frame;fn.argtypes=[C.c_void_p,C.c_uint,C.c_uint,C.c_int,C.c_void_p]
samples=json.loads((WORK/'model/dataset-review.json').read_text())['samples']
x=np.load(WORK/'model/inputs.npy');out=np.zeros(9216,dtype=np.int8);bad=0
for i,row in enumerate(samples):
 raw=(PACKAGE/'dataset'/row['file']).read_bytes();assert hashlib.sha256(raw).hexdigest()==row['sha256']
 status=fn(raw,len(raw),row.get('stride_bytes',640),int(row['byte_order']=='lsb_first'),out.ctypes.data)
 assert status in [0,4],(i,status)
 assert np.array_equal(out,x[i].reshape(-1)),i
 bad+=int(status==4)
r={'samples':len(x),'byte_exact':True,'quality_rejects':bad,
   'scope':'archived reader versus actual production C, all train/validation/test; no labels or thresholds changed'}
(HOST/'preprocessing.json').write_text(json.dumps(r,indent=2));print(json.dumps(r))
