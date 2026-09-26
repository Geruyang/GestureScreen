"""Compare production RGB C preprocessing with frozen training pixels."""
from pathlib import Path
import ctypes as C
import json
import hashlib
import subprocess
import numpy as np
ROOT=Path(__file__).resolve().parents[1];WORK=ROOT/'Build/deployment-v12-20260922'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    source=ROOT/'Modules/Vision/Src/gs_preprocess.c';header=ROOT/'Modules/Vision/Inc/gs_preprocess.h'
    hashes={str(p):sha(p) for p in (source,header)}
    bridge=WORK/'host/preprocess_bridge.c'
    bridge.write_text('#include "gs_preprocess.h"\nint check_frame(const unsigned char *raw,unsigned bytes,unsigned stride,int order,signed char *out) {gs_rgb565_frame_t f={raw,bytes,320,240,stride,(gs_rgb565_byte_order_t)order};return gs_preprocess_rgb565(&f,out,GS_AI_INPUT_SIZE,0,0);}\n',encoding='utf-8')
    dll=WORK/'host/preprocess.dll';gcc=ROOT.parent/'STAI/4.0/Utilities/windows/mingw64/bin/gcc.exe'
    subprocess.run([str(gcc),'-shared','-O2','-I'+str(header.parent),str(bridge),str(source),'-o',str(dll)],check=True)
    lib=C.CDLL(str(dll));fn=lib.check_frame;fn.argtypes=[C.c_void_p,C.c_uint,C.c_uint,C.c_int,C.c_void_p]
    data=json.loads((WORK/'model/export.json').read_text());dataset=Path(data['manifest']).parent
    expected=np.load(WORK/'model/quantized-inputs.npy');out=np.full(27648+8,85,dtype=np.int8);rejected=0
    for i,row in enumerate(data['samples']):
        raw=(dataset/row['file']).read_bytes();assert hashlib.sha256(raw).hexdigest()==row['sha256']
        out.fill(85);status=fn(raw,len(raw),row['stride_bytes'],int(row['byte_order']=='lsb_first'),out.ctypes.data+4)
        assert status in (0,4),(i,status);rejected+=status==4
        assert np.array_equal(out[4:-4],expected[i].reshape(-1)),i
        assert np.all(out[:4]==85) and np.all(out[-4:]==85),i
    for name,digest in hashes.items():assert sha(Path(name))==digest
    record=dict(samples=len(expected),byte_exact_to_frozen_training_inputs=True,guard_bytes_passed=True,
        quality_rejections=rejected,source_sha256=hashes,dll_sha256=sha(dll),test_opened=False)
    (WORK/'host/preprocess-check.json').write_text(json.dumps(record,indent=2),encoding='utf-8');print(json.dumps(record,indent=2))
if __name__=='__main__':main()
