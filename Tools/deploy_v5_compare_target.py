"""Compare one coherently captured Cortex-M4 input/logit pair with the host backend."""
from pathlib import Path
import argparse,ctypes as C,json,hashlib
ROOT=Path(__file__).resolve().parents[1];WORK=ROOT/'Build/deployment-v5'
a=argparse.ArgumentParser();a.add_argument('--input',required=True,type=Path);a.add_argument('--logits',required=True,type=Path)
a.add_argument('--hex-sha256',required=True);a.add_argument('--output',required=True,type=Path);args=a.parse_args()
raw=args.input.read_bytes();target=args.logits.read_bytes()
if len(raw)!=9216 or len(target)!=7:raise ValueError('Expected exactly 9216 input bytes and 7 logits')
lib_path=WORK/'host/production.dll';lib=C.CDLL(str(lib_path));fn=lib.gs_cubeai_execute
fn.argtypes=[C.c_void_p,C.c_size_t,C.c_void_p,C.c_size_t,C.POINTER(C.c_float),C.POINTER(C.c_int32),C.c_void_p,C.c_void_p]
buf=C.create_string_buffer(raw);output=(C.c_int8*7)();scale=C.c_float();zero=C.c_int32()
status=fn(buf,9216,output,7,C.byref(scale),C.byref(zero),None,None)
if status!=0:raise RuntimeError('Host backend failed: '+str(status))
board=list((C.c_int8*7).from_buffer_copy(target));host=list(output)
result={'hex_sha256':args.hex_sha256,'input_file':str(args.input.resolve()),'input_sha256':hashlib.sha256(raw).hexdigest(),'target_logits_sha256':hashlib.sha256(target).hexdigest(),'host_dll_sha256':hashlib.sha256(lib_path.read_bytes()).hexdigest(),'target_logits':board,'host_logits':host,'byte_exact':board==host,'max_logit_delta':max(abs(x-y) for x,y in zip(board,host)),'output_scale':scale.value,'output_zero_point':zero.value,'scope':'one breakpoint-captured input/output pair; coherence must be established by hardware-session evidence; not full-dataset target accuracy or latency measurement'}
args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
